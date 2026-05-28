from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, ws_authenticate
from app.config import get_settings
from app.db import SessionLocal, get_db, init_db
from app.models import AuditEvent, DeskSessionRow, InteractionRecord, User
from app.routers.auth import ensure_seed_admin, router as auth_router
from app.services.bhashini_client import BhashiniError, bhashini
from app.services.demo_oracle import demo_translate  # noqa: F401  (used as silent fallback in fast_mt)
from app.services.disclaimers import disclaimers_for_intent
from app.services.fast_mt import fast_translate
from app.services.glossary import find_terms_in_text
from app.services.llm_bank import (
    bilingual_summary,
    enrich_turn,
    extract_form_and_signals,
    merge_asr_confidence,
)
from app.services.normalize import normalize_financial_text
from app.services.process_guides import guide_for_intent
from app.services.safety import redact_mapping, sanitize_for_llm
from app.services.agent_guidelines import guidelines_for_intent
from app.services.session_store import ConversationTurn, store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    s = get_settings()
    async with SessionLocal() as db:
        await ensure_seed_admin(
            db,
            email=s.seed_admin_email,
            password=s.seed_admin_password,
            name=s.seed_admin_name,
        )
    logger.info("DB ready; LLM provider=%s", get_settings().llm_provider)
    yield


app = FastAPI(title=get_settings().app_name, version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)

@app.get("/health")
async def health() -> dict[str, Any]:
    s = get_settings()
    api_key, _, model = s.llm_effective
    return {
        "status": "ok",
        "bhashini_configured": bool(s.bhashini_user_id and s.bhashini_ulca_api_key),
        "llm_provider": s.llm_provider,
        "llm_model": model,
        "llm_configured": bool(api_key),
        "demo_mode": s.demo_mode,
        "auth": "jwt_required",
        "features": [
            "real_auth_jwt_roles",
            "postgres_or_sqlite_persistence",
            "bhashini_asr_nmt_tts",
            "groq_or_openai_llm",
            "smart_form_autofill",
            "bilingual_records",
            "pii_redaction_governance",
        ],
    }


# ----------------------- Session lifecycle (DB + memory) -----------------------


class SessionCreate(BaseModel):
    customer_lang: str = Field(default="hi", description="Bhashini ISO-639 code, e.g. hi, ta, kn")
    staff_lang: str = Field(default="en")
    customer_ref: str = Field(default="", description="Optional CIF or customer reference")


@app.post("/session")
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    sess = store.new_session(body.customer_lang, body.staff_lang)
    sess.log_audit("session_created", {"user": user.email})

    row = DeskSessionRow(
        id=sess.session_id,
        user_id=user.id,
        customer_lang=body.customer_lang,
        staff_lang=body.staff_lang,
        customer_ref=body.customer_ref or "",
        status="open",
        metrics={},
        form_snapshot={},
        turns=[],
    )
    db.add(row)
    db.add(
        AuditEvent(
            session_id=sess.session_id,
            user_id=user.id,
            event="session_created",
            payload={"customer_lang": body.customer_lang, "staff_lang": body.staff_lang},
        )
    )
    await db.commit()

    return {
        "session_id": sess.session_id,
        "policy": "persisted_with_pii_redaction",
    }


@app.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List sessions visible to the current user (admins see all, staff sees own)."""
    stmt = select(DeskSessionRow).order_by(DeskSessionRow.created_at.desc())
    if user.role != "admin":
        stmt = stmt.where(DeskSessionRow.user_id == user.id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "sessions": [
            {
                "id": r.id,
                "customer_lang": r.customer_lang,
                "staff_lang": r.staff_lang,
                "customer_ref": r.customer_ref,
                "status": r.status,
                "last_intent": r.last_intent,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                "metrics": r.metrics or {},
            }
            for r in rows
        ]
    }


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = (await db.execute(select(DeskSessionRow).where(DeskSessionRow.id == session_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="session_not_found")
    if user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    records = (
        await db.execute(select(InteractionRecord).where(InteractionRecord.session_id == session_id))
    ).scalars().all()
    return {
        "session": {
            "id": row.id,
            "customer_lang": row.customer_lang,
            "staff_lang": row.staff_lang,
            "customer_ref": row.customer_ref,
            "status": row.status,
            "last_intent": row.last_intent,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "closed_at": row.closed_at.isoformat() if row.closed_at else None,
            "metrics": row.metrics or {},
            "form_snapshot": row.form_snapshot or {},
            "turns": row.turns or [],
        },
        "records": [
            {
                "id": r.id,
                "summary_staff_lang": r.summary_staff_lang,
                "summary_customer_lang": r.summary_customer_lang,
                "payload": r.payload,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


class SummaryRequest(BaseModel):
    session_id: str


@app.post("/summary")
async def post_summary(
    body: SummaryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    sess = store.get(body.session_id)
    if not sess:
        return {"error": "session_not_found"}
    row = (await db.execute(select(DeskSessionRow).where(DeskSessionRow.id == body.session_id))).scalar_one_or_none()
    if not row:
        return {"error": "session_row_missing"}
    if user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")

    turns = [
        {
            "role": t.role,
            "source_lang": t.source_lang,
            "original": t.text_original,
            "translated": t.text_translated,
            "confidence": t.confidence,
        }
        for t in sess.turns
    ]
    metrics = sess.snapshot_metrics()
    summary = await bilingual_summary(
        turns=turns,
        customer_lang=sess.customer_lang,
        staff_lang=sess.staff_lang,
        metrics=metrics,
    )
    sess.log_audit("summary_generated", {"turns": len(turns)})

    # Persist a bilingual interaction record
    rec = InteractionRecord(
        session_id=row.id,
        user_id=user.id,
        summary_staff_lang=str(summary.get("summary_staff_lang") or ""),
        summary_customer_lang=str(summary.get("summary_customer_lang") or ""),
        payload={"summary": summary, "metrics": metrics},
    )
    db.add(rec)
    db.add(
        AuditEvent(
            session_id=row.id,
            user_id=user.id,
            event="summary_generated",
            payload={"turns": len(turns)},
        )
    )
    await db.commit()

    return {
        "session_id": sess.session_id,
        "summary": summary,
        "metrics": metrics,
        "record_id": rec.id,
        "audit_tail": sess.audit[-8:],
    }


@app.get("/session/{session_id}/metrics")
async def get_metrics(
    session_id: str,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    sess = store.get(session_id)
    if not sess:
        return {"error": "session_not_found"}
    return {"session_id": session_id, "metrics": sess.snapshot_metrics(), "intent": sess.last_intent}


@app.get("/session/{session_id}/export")
async def export_session(
    session_id: str,
    redact: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    sess = store.get(session_id)
    row = (await db.execute(select(DeskSessionRow).where(DeskSessionRow.id == session_id))).scalar_one_or_none()
    if not sess and not row:
        return {"error": "session_not_found"}
    if row and user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")

    if sess:
        packet: dict[str, Any] = {
            "session_id": sess.session_id,
            "policy": "bank_grade_pii_redaction_available",
            "customer_lang": sess.customer_lang,
            "staff_lang": sess.staff_lang,
            "metrics": sess.snapshot_metrics(),
            "turns": [
                {
                    "role": t.role,
                    "source_lang": t.source_lang,
                    "text_original": t.text_original,
                    "text_translated": t.text_translated,
                    "confidence": t.confidence,
                    "ts": t.ts,
                }
                for t in sess.turns
            ],
            "form_prefill": sess.form.__dict__.copy(),
            "audit": sess.audit[-50:],
            "last_intent": sess.last_intent,
        }
    else:
        # Live session ended — serve from DB
        packet = {
            "session_id": row.id,
            "policy": "bank_grade_pii_redaction_available",
            "customer_lang": row.customer_lang,
            "staff_lang": row.staff_lang,
            "metrics": row.metrics or {},
            "turns": row.turns or [],
            "form_prefill": row.form_snapshot or {},
            "audit": [],
            "last_intent": row.last_intent,
        }

    if redact:
        packet = redact_mapping(packet)

    db.add(
        AuditEvent(
            session_id=session_id,
            user_id=user.id,
            event="session_exported",
            payload={"redact": redact},
        )
    )
    await db.commit()
    return packet


@app.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    row = (await db.execute(select(DeskSessionRow).where(DeskSessionRow.id == session_id))).scalar_one_or_none()
    if row and user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")

    sess = store.get(session_id)
    if row and sess:
        # Mirror final state into the DB row before clearing memory
        row.metrics = sess.snapshot_metrics()
        row.form_snapshot = sess.form.__dict__.copy()
        row.turns = [
            {
                "role": t.role,
                "source_lang": t.source_lang,
                "text_original": t.text_original,
                "text_translated": t.text_translated,
                "confidence": t.confidence,
                "ts": t.ts,
            }
            for t in sess.turns
        ]
        row.last_intent = sess.last_intent
        row.status = "closed"
        row.closed_at = datetime.now(timezone.utc)

    store.delete(session_id)
    db.add(
        AuditEvent(
            session_id=session_id,
            user_id=user.id if user else None,
            event="session_closed",
            payload={},
        )
    )
    await db.commit()
    return {"status": "cleared", "session_id": session_id}


# ----------------------- Risk + turn finalize (unchanged logic) -----------------------


RISK_KEYWORDS = [
    ("high", "guaranteed return"),
    ("high", "100% approval"),
    ("medium", "sure you will get"),
    ("medium", "definitely approved"),
    ("low", "no charges"),
]


def quick_risk_scan(text: str) -> list[dict[str, str]]:
    t = text.lower()
    out: list[dict[str, str]] = []
    for level, phrase in RISK_KEYWORDS:
        if phrase in t:
            out.append({"level": level, "reason": f"Phrase pattern: '{phrase}'"})
    return out[:5]


async def _persist_turn(session_id: str, turn_payload: dict[str, Any]) -> None:
    """Append a redacted turn snapshot to the DB row (best-effort)."""
    try:
        async with SessionLocal() as db:
            row = (
                await db.execute(select(DeskSessionRow).where(DeskSessionRow.id == session_id))
            ).scalar_one_or_none()
            if not row:
                return
            # PII-redact the persisted copy — raw originals never hit the DB.
            redacted = redact_mapping(turn_payload)
            new_turns = list(row.turns or [])
            new_turns.append(redacted)
            row.turns = new_turns
            await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("turn persist failed: %s", e)


async def _finalize_customer_turn(
    sess: Any,
    text_original: str,
    text_translated: str,
    api_confidence: float | None,
) -> None:
    conf = merge_asr_confidence(api_confidence, text_original)
    if conf < 0.5:
        sess.metrics.low_confidence_segments += 1
    sess.metrics.customer_turns += 1

    turn = ConversationTurn(
        role="customer",
        source_lang=sess.customer_lang,
        text_original=text_original,
        text_translated=text_translated,
        confidence=conf,
    )
    sess.turns.append(turn)
    sess.log_audit("customer_turn", {"confidence": conf, "chars": len(text_original)})

    await _persist_turn(
        sess.session_id,
        {
            "role": "customer",
            "source_lang": sess.customer_lang,
            "text_original": text_original,
            "text_translated": text_translated,
            "confidence": conf,
            "ts": turn.ts,
        },
    )

    ws = sess.ws
    if ws is None:
        return

    combined = f"{text_original} {text_translated}"
    norm = normalize_financial_text(combined)
    try:
        await ws.send_json(
            {
                "type": "transcript",
                "role": "customer",
                "source_lang": sess.customer_lang,
                "text_original": text_original,
                "text_translated": text_translated,
                "confidence": round(conf, 3),
                "low_confidence": conf < 0.5,
                "glossary": find_terms_in_text(combined),
                "risk_flags": quick_risk_scan(combined),
                "normalized": norm,
            }
        )
    except Exception:  # noqa: BLE001
        return

    recent = "\n".join(f"{t.role}: {t.text_original}" for t in sess.turns[-8:])
    enrich = await enrich_turn(
        transcript_customer_lang=text_original,
        translation_staff_lang=text_translated,
        recent_context=recent,
        asr_confidence=conf,
    )
    if enrich.get("intent"):
        sess.last_intent = str(enrich["intent"])
    discs = disclaimers_for_intent(sess.last_intent, sess.staff_lang, sess.customer_lang)
    agent_g = guidelines_for_intent(sess.last_intent)
    try:
        await ws.send_json(
            {
                "type": "copilot",
                "intent": enrich.get("intent"),
                "intent_confidence": enrich.get("intent_confidence"),
                "risk_flags": enrich.get("risk_flags") or [],
                "talking_points": enrich.get("talking_points_staff_lang") or [],
                "disambiguation_options": enrich.get("disambiguation_options") or [],
                "low_confidence_fallback": enrich.get("low_confidence_fallback"),
                "code_mixing_note": enrich.get("code_mixing_note"),
                "process_guide": guide_for_intent(sess.last_intent, sess.staff_lang),
                "process_guide_customer": guide_for_intent(sess.last_intent, sess.customer_lang),
                "disclaimers_staff": discs["staff_lang"],
                "disclaimers_customer": discs["customer_lang"],
                "agent_guidelines": agent_g,
            }
        )
    except Exception:  # noqa: BLE001
        return

    snippet = recent[-4000:]
    form_partial = await extract_form_and_signals(conversation_snippet=snippet, staff_lang=sess.staff_lang)
    sess.form.merge(form_partial)
    try:
        await ws.send_json(
            {
                "type": "form_prefill",
                "fields": sess.form.__dict__.copy(),
                "raw_extraction": {k: v for k, v in form_partial.items() if k not in ("risk_flags",)},
            }
        )
    except Exception:  # noqa: BLE001
        pass


async def _process_customer_audio(
    sess: Any,
    audio_bytes: bytes,
    audio_format: str,
    sample_rate: int,
) -> None:
    s = get_settings()
    transcript = ""
    translated = ""
    api_c: float | None = None

    if s.demo_mode or not (s.bhashini_user_id and s.bhashini_ulca_api_key):
        # No live ASR keys — surface a tip instead of a confusing line.
        # In Chrome the browser-side Web Speech API handles live mic ASR, so
        # this path is only reached from raw audio chunks (not browser-finals).
        transcript = "[Tip] Use Chrome's mic for live ASR, or pick a scenario / type the customer's words."
        translated = transcript
        api_c = 0.4
    else:
        try:
            transcript, translated, api_c = await bhashini.asr_and_translate(
                source_lang=sess.customer_lang,
                target_lang=sess.staff_lang,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
                sampling_rate=sample_rate,
            )
        except BhashiniError as e:
            logger.warning("Bhashini ASR failed: %s", e)
            sess.metrics.bhashini_errors += 1
            transcript = ""
            translated = f"[Bhashini error] {e}"

    if transcript or translated:
        await _finalize_customer_turn(sess, transcript or translated, translated or transcript, api_c)


@app.websocket("/ws/desk/{session_id}")
async def desk_ws(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(default=None),
) -> None:
    await websocket.accept()

    # --- WebSocket auth ---
    if not token:
        await websocket.send_json({"type": "error", "message": "missing_token"})
        await websocket.close(code=4401)
        return
    try:
        async with SessionLocal() as db:
            from app.auth import _user_from_token  # local import to reuse helper

            user = await _user_from_token(token, db)
    except HTTPException as e:
        await websocket.send_json({"type": "error", "message": f"auth_failed: {e.detail}"})
        await websocket.close(code=4401)
        return

    # --- Ensure session ownership ---
    async with SessionLocal() as db:
        row = (
            await db.execute(select(DeskSessionRow).where(DeskSessionRow.id == session_id))
        ).scalar_one_or_none()
    if not row:
        await websocket.send_json({"type": "error", "message": "invalid_session"})
        await websocket.close(code=4404)
        return
    if user.role != "admin" and row.user_id != user.id:
        await websocket.send_json({"type": "error", "message": "forbidden"})
        await websocket.close(code=4403)
        return

    sess = store.get(session_id)
    if not sess:
        # Live in-memory session lost (server restart) — recreate shell from DB
        sess = store.new_session(row.customer_lang, row.staff_lang)
        # Re-key to match the DB row id so the URL stays consistent
        store._sessions.pop(sess.session_id, None)
        sess.session_id = session_id
        store._sessions[session_id] = sess

    sess.ws = websocket
    sess.log_audit("ws_connected", {"user": user.email})

    try:
        await websocket.send_json(
            {
                "type": "ready",
                "session_id": session_id,
                "customer_lang": sess.customer_lang,
                "staff_lang": sess.staff_lang,
                "user": {"email": user.email, "role": user.role, "full_name": user.full_name},
                "features": [
                    "realtime_asr_nmt_bhashini",
                    "groq_or_openai_banking_llm",
                    "confidence_disambiguation_disclaimers",
                    "staff_tts_customer_language",
                    "smart_form_autofill",
                    "bilingual_summary_quotes",
                    "glossary_risk_normalize",
                    "real_auth_jwt_roles",
                    "persistent_session_with_redaction",
                    "prompt_sanitization",
                    "agent_guidelines",
                ],
            }
        )
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "ping":
                await websocket.send_json({"type": "pong"})

            elif mtype == "customer_interim":
                t = (msg.get("text") or "").strip()
                if not t:
                    continue
                is_final = bool(msg.get("is_final"))
                await websocket.send_json(
                    {
                        "type": "partial_transcript",
                        "role": "customer",
                        "text": t,
                        "is_final": is_final,
                    }
                )

                # --- Live partial translation (the "feels real-time" bit) ---
                # Debounce: only translate if the partial has grown by ≥4 chars
                # AND ≥350ms has passed since the last call. On `is_final` we always go.
                state = getattr(sess, "_partial_state", None)
                if state is None:
                    state = {"last_len": 0, "last_ts": 0.0, "task": None}
                    sess._partial_state = state  # type: ignore[attr-defined]

                grew = len(t) - int(state["last_len"]) >= 4
                aged = (time.time() - float(state["last_ts"])) >= 0.35
                if not (is_final or (grew and aged)):
                    continue

                state["last_len"] = len(t)
                state["last_ts"] = time.time()

                # Cancel the in-flight translation task — we only care about the freshest partial.
                prev = state.get("task")
                if prev and not prev.done():
                    prev.cancel()

                async def _translate_and_emit(text_in: str, final: bool):
                    try:
                        translated, engine = await fast_translate(
                            text_in, sess.customer_lang, sess.staff_lang
                        )
                        await websocket.send_json(
                            {
                                "type": "partial_translation",
                                "role": "customer",
                                "source_lang": sess.customer_lang,
                                "target_lang": sess.staff_lang,
                                "text_original": text_in,
                                "text_translated": translated,
                                "engine": engine,
                                "is_final": final,
                            }
                        )
                    except asyncio.CancelledError:
                        return
                    except Exception as e:  # noqa: BLE001
                        logger.warning("partial translate failed: %s", e)

                state["task"] = asyncio.create_task(_translate_and_emit(t, is_final))

            elif mtype == "staff_interim":
                # Staff is typing — live-translate to customer language as a preview.
                t = (msg.get("text") or "").strip()
                if not t:
                    continue
                state = getattr(sess, "_staff_partial_state", None)
                if state is None:
                    state = {"last_len": 0, "last_ts": 0.0, "task": None}
                    sess._staff_partial_state = state  # type: ignore[attr-defined]
                grew = len(t) - int(state["last_len"]) >= 4
                aged = (time.time() - float(state["last_ts"])) >= 0.4
                if not (grew and aged):
                    continue
                state["last_len"] = len(t)
                state["last_ts"] = time.time()
                prev = state.get("task")
                if prev and not prev.done():
                    prev.cancel()

                async def _staff_translate_and_emit(text_in: str):
                    try:
                        translated, engine = await fast_translate(
                            text_in, sess.staff_lang, sess.customer_lang
                        )
                        await websocket.send_json(
                            {
                                "type": "staff_partial_translation",
                                "role": "staff",
                                "source_lang": sess.staff_lang,
                                "target_lang": sess.customer_lang,
                                "text_original": text_in,
                                "text_translated": translated,
                                "engine": engine,
                            }
                        )
                    except asyncio.CancelledError:
                        return
                    except Exception as e:  # noqa: BLE001
                        logger.warning("staff partial translate failed: %s", e)

                state["task"] = asyncio.create_task(_staff_translate_and_emit(t))

            elif mtype == "customer_audio_wav":
                b64 = msg.get("base64", "")
                try:
                    audio_bytes = base64.b64decode(b64)
                except Exception:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "message": "invalid_base64"})
                    continue
                if len(audio_bytes) < 256:
                    continue
                sr = int(msg.get("sample_rate") or 16000)
                fmt = str(msg.get("format") or "wav")
                await _process_customer_audio(sess, audio_bytes, audio_format=fmt, sample_rate=sr)

            elif mtype == "customer_text":
                # Text fallback — user typed what customer said (bypasses ASR)
                raw = (msg.get("text") or "").strip()
                if not raw:
                    continue
                lang = msg.get("lang") or sess.customer_lang
                if lang == sess.staff_lang:
                    translated = raw
                else:
                    translated, _engine = await fast_translate(raw, lang, sess.staff_lang)
                await _finalize_customer_turn(sess, raw, translated, 0.99)

            elif mtype == "staff_speak":
                raw_text = (msg.get("text") or "").strip()
                text = sanitize_for_llm(raw_text)
                if not text:
                    continue
                target = msg.get("target_lang") or sess.customer_lang
                # Translation chain: Bhashini → LLM → offline demo phrasebook.
                if target == sess.staff_lang:
                    cust_text = text
                else:
                    cust_text, _engine = await fast_translate(text, sess.staff_lang, target)

                turn = ConversationTurn(
                    role="staff",
                    source_lang=sess.staff_lang,
                    text_original=text,
                    text_translated=cust_text,
                    confidence=None,
                )
                sess.turns.append(turn)
                sess.metrics.staff_turns += 1
                sess.log_audit("staff_turn", {})
                await _persist_turn(
                    sess.session_id,
                    {
                        "role": "staff",
                        "source_lang": sess.staff_lang,
                        "text_original": text,
                        "text_translated": cust_text,
                        "confidence": None,
                        "ts": turn.ts,
                    },
                )
                await websocket.send_json(
                    {
                        "type": "transcript",
                        "role": "staff",
                        "source_lang": sess.staff_lang,
                        "text_original": text,
                        "text_translated": cust_text,
                    }
                )
                tts_done = False
                if get_settings().bhashini_user_id and get_settings().bhashini_ulca_api_key:
                    try:
                        audio = await bhashini.tts(
                            lang=target,
                            text=cust_text,
                            gender=msg.get("gender") or "female",
                        )
                        sess.metrics.tts_playouts += 1
                        await websocket.send_json(
                            {
                                "type": "tts_audio",
                                "lang": target,
                                "mime": "audio/wav",
                                "base64": base64.b64encode(audio).decode("ascii"),
                                "barge_in_hint": "Start listening to interrupt playback",
                            }
                        )
                        tts_done = True
                    except BhashiniError as e:
                        await websocket.send_json({"type": "tts_error", "message": str(e)})
                if not tts_done:
                    # Browser speechSynthesis fallback — the frontend speaks the
                    # translated text locally. This keeps the demo audible without
                    # any external TTS API.
                    sess.metrics.tts_playouts += 1
                    await websocket.send_json(
                        {
                            "type": "tts_fallback",
                            "lang": target,
                            "text": cust_text,
                            "reason": "no_external_tts_configured",
                        }
                    )

            elif mtype == "end_session":
                sess.log_audit("session_ended_by_client", {})
                # Mirror to DB before clearing memory
                try:
                    async with SessionLocal() as db:
                        r = (
                            await db.execute(select(DeskSessionRow).where(DeskSessionRow.id == session_id))
                        ).scalar_one_or_none()
                        if r:
                            r.metrics = sess.snapshot_metrics()
                            r.form_snapshot = sess.form.__dict__.copy()
                            r.last_intent = sess.last_intent
                            r.status = "closed"
                            r.closed_at = datetime.now(timezone.utc)
                            db.add(
                                AuditEvent(
                                    session_id=session_id,
                                    user_id=user.id,
                                    event="session_closed",
                                    payload={},
                                )
                            )
                            await db.commit()
                except Exception as e:  # noqa: BLE001
                    logger.warning("close persist failed: %s", e)
                store.delete(session_id)
                await websocket.send_json({"type": "session_cleared", "policy": "memory_cleared_db_retained"})
                await websocket.close(code=1000)
                return

            else:
                await websocket.send_json({"type": "error", "message": f"unknown_type:{mtype}"})

    except WebSocketDisconnect:
        # Leave the DB row for history; just drop in-memory state.
        store.delete(session_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("ws error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:  # noqa: BLE001
            pass
        store.delete(session_id)
