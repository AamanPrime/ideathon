from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
import base64
import os
import logging
from typing import Optional
from app.config import get_settings
from google import genai
from google.genai import types

router = APIRouter()
logger = logging.getLogger(__name__)

# Locate the Google Cloud service-account credentials (gitignored, never
# committed). Resolution order:
#   1. settings.google_application_credentials (relative to backend/ or absolute)
#   2. any *service_account*.json or known filename in backend/
#   3. GOOGLE_APPLICATION_CREDENTIALS / GOOGLE_CLOUD_PROJECT env vars
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _locate_credentials() -> Optional[str]:
    s = get_settings()
    candidates: list[Path] = []
    cfg = (s.google_application_credentials or "").strip()
    if cfg:
        p = Path(cfg)
        candidates.append(p if p.is_absolute() else _BACKEND_DIR / p)
    # Known/legacy filenames + any service-account JSON in backend/
    candidates.append(_BACKEND_DIR / "gcp_service_account.json")
    candidates.append(_BACKEND_DIR / "annular-form-477012-i9-ba572b97d622.json")
    candidates.extend(sorted(_BACKEND_DIR.glob("*service_account*.json")))
    for c in candidates:
        if c and c.exists():
            return str(c)
    return None


CREDENTIALS_FILE = _locate_credentials()
PROJECT_ID = get_settings().gemini_project_id or "annular-form-477012-i9"
if CREDENTIALS_FILE:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            creds_data = json.load(f)
            PROJECT_ID = creds_data.get("project_id", PROJECT_ID)
    except Exception as e:
        logger.error(f"Failed to load credentials file: {e}")
else:
    PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
    logger.warning("No GCP service-account JSON found; Vertex Live will fail until one is added to backend/")

LANG_MAP = {
    "gu": "Gujarati",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "bn": "Bengali",
    "pa": "Punjabi",
    "or": "Odia",
    "en": "English",
}

@router.websocket("/ws/live-translate")
async def live_translate_ws(
    websocket: WebSocket,
    source_lang: str = "Hindi",
    target_lang: str = "English",
    session_id: Optional[str] = None
):
    await websocket.accept()
    
    settings = get_settings()
    
    source_name = LANG_MAP.get(source_lang.lower(), source_lang)
    if source_lang.lower() == "none":
        source_name = "any language (like Hindi, Gujarati, Tamil, Kannada, Malayalam, Marathi, Bengali, Telugu, Punjabi, Odia)"
    target_name = LANG_MAP.get(target_lang.lower(), target_lang)

    # 1. Live Session Config: fast turn detection, each utterance is independent
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                silence_duration_ms=500,
                prefix_padding_ms=200,
            )
        ),
        system_instruction=types.Content(
            parts=[
                types.Part(
                    text=(
                        f"You are a real-time two-way speech translator at a bank branch desk.\n\n"
                        f"The customer speaks {source_name}; the staff speaks {target_name}.\n\n"
                        f"RULES:\n"
                        f"1. Automatically DETECT the language of every utterance you hear.\n"
                        f"2. If you hear the customer's language (anything that is not {target_name}), translate "
                        f"it into {target_name} and speak it aloud.\n"
                        f"3. If you hear {target_name} (the staff), translate it into the customer's language and "
                        f"speak it aloud. The customer's language is whatever language the customer ACTUALLY "
                        f"spoke in their most recent utterance — for example, if the customer spoke Gujarati, "
                        f"reply in Gujarati; if Tamil, reply in Tamil.\n"
                        f"4. CRITICAL: NEVER assume or default to Hindi. Only use Hindi if the customer actually "
                        f"spoke Hindi. Mirror the customer's exact detected language for every reply to the staff.\n"
                        f"5. ALWAYS produce the translation as spoken audio, in BOTH directions.\n"
                        f"6. Output ONLY the translation. NEVER greet, introduce yourself, comment, explain, or "
                        f"add any words beyond the translation. NEVER repeat the original.\n"
                        f"7. Keep translations natural and concise, then wait silently for the next utterance.\n"
                        f"8. Do not carry conversation content between turns — the only thing you remember is "
                        f"which language the customer is speaking."
                    )
                )
            ]
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig()
    )

    model_name = settings.gemini_model if settings.gemini_model else "gemini-live-2.5-flash-native-audio"
    
    # Initialize strict Vertex AI Client
    try:
        logger.info(f"Attempting Vertex AI Client initialization for project {PROJECT_ID}...")
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="us-central1"
        )
    except Exception as e:
        logger.error(f"Failed to initialize Vertex AI client: {e}")
        await websocket.send_json({"type": "error", "message": f"Vertex AI Client creation failed: {e}"})
        await websocket.close()
        return

    logger.info(f"Establishing Vertex AI Live connection for {model_name}...")
    try:
        async with client.aio.live.connect(model=model_name, config=config) as session:
            logger.info("Successfully connected to Vertex AI Live Session!")
            await websocket.send_json({"type": "ready"})

            # Local import to prevent circular dependency
            from app.main import _finalize_customer_turn, _finalize_staff_turn
            from app.services.session_store import store
            
            sess = store.get(session_id) if session_id else None

            # Track background finalization tasks so they don't block audio
            _bg_tasks: set[asyncio.Task] = set()

            # Helper to detect if a turn belongs to the staff
            def is_staff_turn(text: str, src: str, tgt: str) -> bool:
                src_is_en = (src.lower() in ("en", "english"))
                tgt_is_en = (tgt.lower() in ("en", "english"))
                if src_is_en and not tgt_is_en:
                    is_latin = all(ord(c) < 128 or c.isspace() or c in ".,!?;:'\"()-" for c in text)
                    return not is_latin
                if tgt_is_en and not src_is_en:
                    is_latin = all(ord(c) < 128 or c.isspace() or c in ".,!?;:'\"()-" for c in text)
                    return is_latin
                return all(ord(c) < 128 or c.isspace() or c in ".,!?;:'\"()-" for c in text)

            def _fire_and_forget(coro):
                """Schedule a coroutine as a background task that never blocks the audio loop."""
                task = asyncio.create_task(coro)
                _bg_tasks.add(task)
                task.add_done_callback(lambda t: _bg_tasks.discard(t))

            class TurnState:
                def __init__(self):
                    self.input_text = ""
                    self.output_text = ""
                    self.input_finished = False
                    self.output_finished = False
                    # None = unknown yet, True = staff→customer (speak audio),
                    # False = customer→staff (text only, suppress audio)
                    self.is_staff = None

            turn_state = TurnState()

            # Transcript throttle: max 1 send per 150ms to avoid flooding the WS
            import time
            _last_transcript_send = 0.0
            _TRANSCRIPT_THROTTLE_S = 0.15

            def finalize_turn_if_complete():
                """Non-blocking: fires finalization as a background task."""
                nonlocal turn_state
                inp = turn_state.input_text.strip()
                outp = turn_state.output_text.strip()
                
                if turn_state.input_finished and turn_state.output_finished and inp:
                    if sess:
                        if is_staff_turn(inp, source_lang, target_lang):
                            _fire_and_forget(_finalize_staff_turn(sess, inp, outp))
                        else:
                            _fire_and_forget(_finalize_customer_turn(sess, inp, outp, 0.99))
                    turn_state = TurnState()

            async def _send_transcript_throttled(force: bool = False):
                """Send transcript update, throttled to avoid flooding."""
                nonlocal _last_transcript_send
                now = time.monotonic()
                if not force and (now - _last_transcript_send) < _TRANSCRIPT_THROTTLE_S:
                    return
                _last_transcript_send = now
                try:
                    await websocket.send_json({
                        "type": "live_transcript",
                        "input_text": turn_state.input_text,
                        "output_text": turn_state.output_text,
                        "input_finished": turn_state.input_finished,
                        "output_finished": turn_state.output_finished
                    })
                except Exception:
                    pass

            async def receive_from_client():
                try:
                    while True:
                        msg = await websocket.receive_json()
                        if msg.get("type") == "audio_chunk":
                            b64_data = msg.get("data")
                            if b64_data:
                                audio_bytes = base64.b64decode(b64_data)
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=audio_bytes,
                                        mime_type="audio/pcm;rate=16000"
                                    )
                                )
                except WebSocketDisconnect:
                    logger.info("Client disconnected from WebSocket proxy")
                except Exception as e:
                    logger.error(f"Error reading client audio stream: {e}")

            async def _continuous_receive():
                """session.receive() yields a single turn then stops (it breaks on
                turn_complete). Re-enter it in a loop so every subsequent utterance
                keeps getting transcribed/translated for the life of the connection."""
                while True:
                    async for r in session.receive():
                        yield r

            async def receive_from_gemini():
                nonlocal turn_state
                try:
                    async for response in _continuous_receive():
                        server_content = response.server_content
                        if server_content is None:
                            continue

                        # 1. Handle Interruption
                        if server_content.interrupted:
                            try:
                                await websocket.send_json({"type": "interrupted"})
                            except Exception:
                                pass
                            inp = turn_state.input_text.strip()
                            outp = turn_state.output_text.strip()
                            if inp and sess:
                                if is_staff_turn(inp, source_lang, target_lang):
                                    _fire_and_forget(_finalize_staff_turn(sess, inp, outp))
                                else:
                                    _fire_and_forget(_finalize_customer_turn(sess, inp, outp, 0.99))
                            turn_state = TurnState()
                            continue

                        # 2. Handle User Input Audio Transcription
                        if server_content.input_transcription:
                            tx = server_content.input_transcription
                            if tx.text:
                                turn_state.input_text = tx.text
                                turn_state.input_finished = bool(tx.finished)
                                # Classify who is speaking from the transcript's script.
                                # Staff speak the target (English) → spoken audio reply.
                                # Customer speak a regional language → text only for staff.
                                turn_state.is_staff = is_staff_turn(tx.text, source_lang, target_lang)
                                # Force-send when finished, throttle otherwise
                                await _send_transcript_throttled(force=turn_state.input_finished)
                                finalize_turn_if_complete()

                        # 3. Handle Model Output Audio Transcription (translated text)
                        if server_content.output_transcription:
                            tx = server_content.output_transcription
                            if tx.text:
                                turn_state.output_text += tx.text
                                turn_state.output_finished = bool(tx.finished)
                                await _send_transcript_throttled(force=turn_state.output_finished)
                                finalize_turn_if_complete()

                        # 4. Handle Model Output Audio Data Chunks — HIGHEST PRIORITY
                        # Bidirectional: speak every translation aloud, both
                        # customer→staff and staff→customer.
                        model_turn = server_content.model_turn
                        if model_turn is not None:
                            for part in model_turn.parts:
                                if part.inline_data:
                                    audio_data = part.inline_data.data
                                    if audio_data:
                                        if isinstance(audio_data, bytes):
                                            audio_b64 = base64.b64encode(audio_data).decode("utf-8")
                                        else:
                                            audio_b64 = audio_data
                                        try:
                                            await websocket.send_json({
                                                "type": "audio_response",
                                                "data": audio_b64
                                            })
                                        except Exception:
                                            return  # Client gone, stop

                        # 5. Turn finished — finalize the record and RESET so the next
                        # utterance starts clean. output_transcription.finished is not
                        # reliably sent, so turn_complete is the authoritative boundary
                        # (otherwise output_text accumulates across turns).
                        if server_content.turn_complete:
                            inp = turn_state.input_text.strip()
                            outp = turn_state.output_text.strip()
                            if inp and sess:
                                if is_staff_turn(inp, source_lang, target_lang):
                                    _fire_and_forget(_finalize_staff_turn(sess, inp, outp))
                                else:
                                    _fire_and_forget(_finalize_customer_turn(sess, inp, outp, 0.99))
                            turn_state.input_finished = True
                            turn_state.output_finished = True
                            await _send_transcript_throttled(force=True)
                            turn_state = TurnState()
                except Exception as e:
                    logger.error(f"Error reading from Gemini Live Session: {e}")

            # Run both streaming listeners concurrently
            try:
                await asyncio.gather(
                    receive_from_client(),
                    receive_from_gemini()
                )
            finally:
                # Clean up any pending background finalization tasks
                for t in _bg_tasks:
                    t.cancel()
                if _bg_tasks:
                    await asyncio.gather(*_bg_tasks, return_exceptions=True)

    except Exception as e:
        logger.error(f"Vertex AI connection failure: {e}")
        try:
            err_msg = str(e)
            if "not found" in err_msg or "access" in err_msg or "404" in err_msg or "1008" in err_msg:
                friendly_msg = (
                    "Vertex AI Live API is not enabled in your Google Cloud Project 'annular-form-477012-i9', "
                    "or Generative AI model onboarding has not been completed. Please enable Vertex AI in GCP Console."
                )
            else:
                friendly_msg = f"Failed to connect to AI Translator: {err_msg}"
            await websocket.send_json({"type": "error", "message": friendly_msg})
            await websocket.close()
        except:
            pass
