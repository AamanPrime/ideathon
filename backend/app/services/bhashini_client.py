from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class BhashiniError(RuntimeError):
    pass


def _cfg_headers() -> dict[str, str]:
    s = get_settings()
    h: dict[str, str] = {"Content-Type": "application/json"}
    if s.bhashini_user_id:
        h["userID"] = s.bhashini_user_id
    if s.bhashini_ulca_api_key:
        h["ulcaApiKey"] = s.bhashini_ulca_api_key
    return h


def _pick_asr_service(prc: list[dict[str, Any]], source_lang: str) -> dict[str, Any] | None:
    for block in prc:
        if block.get("taskType") != "asr":
            continue
        for c in block.get("config") or []:
            lang = (c.get("language") or {}).get("sourceLanguage")
            if lang == source_lang:
                return c
    return None


def _pick_translation_service(prc: list[dict[str, Any]], source_lang: str, target_lang: str) -> dict[str, Any] | None:
    for block in prc:
        if block.get("taskType") != "translation":
            continue
        for c in block.get("config") or []:
            lang = c.get("language") or {}
            if lang.get("sourceLanguage") == source_lang and lang.get("targetLanguage") == target_lang:
                return c
    return None


def _pick_tts_service(prc: list[dict[str, Any]], lang: str) -> dict[str, Any] | None:
    for block in prc:
        if block.get("taskType") != "tts":
            continue
        for c in block.get("config") or []:
            if (c.get("language") or {}).get("sourceLanguage") == lang:
                return c
    return None


def _inference_auth(endpoint: dict[str, Any]) -> tuple[str, dict[str, str]]:
    url = endpoint.get("callbackUrl") or endpoint.get("callbackURL") or ""
    auth = endpoint.get("inferenceApiKey") or {}
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if isinstance(auth, dict):
        name = auth.get("name") or "Authorization"
        value = auth.get("value")
        if name and value:
            headers[name] = value
    return url, headers


def _parse_compute_transcript(data: dict[str, Any]) -> tuple[str, str, float | None]:
    transcript, translated = "", ""
    confidence: float | None = None
    for task in data.get("pipelineResponse", []) or []:
        for o in task.get("output", []) or []:
            if o.get("source"):
                transcript = str(o["source"])
            if o.get("target"):
                translated = str(o["target"])
            for k in ("score", "confidence", "asrScore", "asr_score", "asrConfidence"):
                if k in o and o[k] is not None:
                    try:
                        confidence = float(o[k])
                    except (TypeError, ValueError):
                        pass
    return transcript, translated, confidence


class BhashiniClient:
    """ULCA pipeline config + compute (ASR, NMT, TTS). Demo-safe when keys unset."""

    def __init__(self) -> None:
        self._cfg_cache: dict[str, dict[str, Any]] = {}

    def _cache_key(self, tasks: str, source: str, target: str) -> str:
        return f"{tasks}|{source}|{target}"

    async def fetch_pipeline_config(self, pipeline_tasks: list[dict[str, Any]]) -> dict[str, Any]:
        s = get_settings()
        if not s.bhashini_user_id or not s.bhashini_ulca_api_key:
            raise BhashiniError("Bhashini credentials not configured (BHASHINI_USER_ID / BHASHINI_ULCA_API_KEY)")

        key = json.dumps(pipeline_tasks, sort_keys=True)
        if key in self._cfg_cache:
            return self._cfg_cache[key]

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                s.bhashini_pipeline_config_url,
                headers=_cfg_headers(),
                json={"pipelineTasks": pipeline_tasks},
            )
            if r.status_code >= 400:
                raise BhashiniError(f"Pipeline config HTTP {r.status_code}: {r.text[:600]}")
            data = r.json()

        self._cfg_cache[key] = data
        return data

    async def asr_and_translate(
        self,
        *,
        source_lang: str,
        target_lang: str,
        audio_bytes: bytes,
        audio_format: str = "wav",
        sampling_rate: int = 16000,
    ) -> tuple[str, str, float | None]:
        req_tasks = [
            {"taskType": "asr", "config": {"language": {"sourceLanguage": source_lang}}},
            {
                "taskType": "translation",
                "config": {
                    "language": {"sourceLanguage": source_lang, "targetLanguage": target_lang},
                },
            },
        ]
        cfg = await self.fetch_pipeline_config(req_tasks)
        prc = cfg.get("pipelineResponseConfig") or []
        endpoint = cfg.get("pipelineInferenceAPIEndPoint") or {}
        url, headers = _inference_auth(endpoint)
        if not url:
            raise BhashiniError("Missing pipelineInferenceAPIEndPoint.callbackUrl")

        asr_c = _pick_asr_service(prc, source_lang)
        tr_c = _pick_translation_service(prc, source_lang, target_lang)
        if not asr_c or not tr_c:
            raise BhashiniError(
                f"No ASR/translation service for {source_lang}->{target_lang}. "
                "Check language pair support in Bhashini portal."
            )

        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        body = {
            "pipelineTasks": [
                {
                    "taskType": "asr",
                    "config": {
                        "language": {"sourceLanguage": source_lang},
                        "serviceId": asr_c.get("serviceId"),
                        "audioFormat": audio_format,
                        "samplingRate": sampling_rate,
                    },
                },
                {
                    "taskType": "translation",
                    "config": {
                        "language": {
                            "sourceLanguage": source_lang,
                            "targetLanguage": target_lang,
                        },
                        "serviceId": tr_c.get("serviceId"),
                    },
                },
            ],
            "inputData": {
                "input": [{"source": None}],
                "audio": [{"audioContent": audio_b64}],
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                raise BhashiniError(f"ASR+NMT HTTP {r.status_code}: {r.text[:800]}")
            data = r.json()
        return _parse_compute_transcript(data)

    async def translate_text(self, *, source_lang: str, target_lang: str, text: str) -> str:
        req_tasks = [
            {
                "taskType": "translation",
                "config": {
                    "language": {"sourceLanguage": source_lang, "targetLanguage": target_lang},
                },
            }
        ]
        cfg = await self.fetch_pipeline_config(req_tasks)
        prc = cfg.get("pipelineResponseConfig") or []
        endpoint = cfg.get("pipelineInferenceAPIEndPoint") or {}
        url, headers = _inference_auth(endpoint)
        tr_c = _pick_translation_service(prc, source_lang, target_lang)
        if not tr_c or not url:
            raise BhashiniError("Translation service unavailable")

        body = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {
                        "language": {
                            "sourceLanguage": source_lang,
                            "targetLanguage": target_lang,
                        },
                        "serviceId": tr_c.get("serviceId"),
                    },
                }
            ],
            "inputData": {
                "input": [{"source": text}],
                "audio": [{"audioContent": None}],
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                raise BhashiniError(f"Translation HTTP {r.status_code}: {r.text[:800]}")
            data = r.json()
        _, translated, _conf = _parse_compute_transcript(data)
        return translated or text

    async def tts(self, *, lang: str, text: str, gender: str = "female") -> bytes:
        req_tasks = [
            {"taskType": "tts", "config": {"language": {"sourceLanguage": lang}}},
        ]
        cfg = await self.fetch_pipeline_config(req_tasks)
        prc = cfg.get("pipelineResponseConfig") or []
        endpoint = cfg.get("pipelineInferenceAPIEndPoint") or {}
        url, headers = _inference_auth(endpoint)
        tts_c = _pick_tts_service(prc, lang)
        if not tts_c or not url:
            raise BhashiniError("TTS service unavailable")

        body = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": lang},
                        "serviceId": tts_c.get("serviceId"),
                        "gender": gender,
                    },
                }
            ],
            "inputData": {
                "input": [{"source": text}],
                "audio": [{"audioContent": None}],
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                raise BhashiniError(f"TTS HTTP {r.status_code}: {r.text[:800]}")
            data = r.json()

        audio_b64 = None
        for task in data.get("pipelineResponse", []) or []:
            for o in task.get("audio", []) or []:
                audio_b64 = o.get("audioContent") or audio_b64
            for o in task.get("output", []) or []:
                audio_b64 = o.get("audioContent") or audio_b64
        if not audio_b64:
            raise BhashiniError(f"No audio in TTS response: {json.dumps(data)[:400]}")
        return base64.b64decode(audio_b64)


bhashini = BhashiniClient()
