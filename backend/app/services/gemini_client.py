"""Google Gemini client — real-time translation + banking JSON enrichment.

Uses the public Generative Language REST endpoint (`generativelanguage.googleapis.com`)
with the API key from settings. Thinking is disabled (`thinkingBudget: 0`) so latency
stays in the ~1s band suitable for live captions.

Design notes
------------
* The configured `GEMINI_MODEL` (`gemini-live-2.5-flash-native-audio`) is a Live
  websocket-only model and cannot serve `generateContent`. For text translation /
  JSON enrichment we use a fast text model (`gemini-2.5-flash`) instead. The Live
  model name is preserved in settings for the streaming-audio path.
* All calls are best-effort: any error returns an empty result so the caller can
  fall through to the next engine (MyMemory / LLM / offline phrasebook).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Fast text model for translation/enrichment (the Live model is audio-websocket only).
_TEXT_MODEL = "gemini-2.5-flash"

# Friendly language names so Gemini gets unambiguous instructions.
_LANG_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "gu": "Gujarati",
    "mr": "Marathi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "or": "Odia",
    "as": "Assamese",
    "ur": "Urdu",
}


def _lang_name(code: str) -> str:
    return _LANG_NAMES.get((code or "").lower(), code or "the target language")


async def _generate(
    prompt: str,
    *,
    system: Optional[str] = None,
    json_mode: bool = False,
    max_tokens: int = 512,
    timeout: float = 8.0,
) -> str:
    """Single-shot generateContent call. Returns raw text ("" on any failure)."""
    s = get_settings()
    if not s.gemini_enabled:
        return ""

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": max_tokens,
            # Disable "thinking" to keep latency low for live captions.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    url = f"{_API_BASE}/{_TEXT_MODEL}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                url,
                headers={
                    "x-goog-api-key": s.gemini_api_key,
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if r.status_code >= 400:
                logger.info("Gemini HTTP %s: %s", r.status_code, r.text[:200])
                return ""
            data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text
    except Exception as e:  # noqa: BLE001
        logger.info("Gemini call failed: %s", e)
        return ""


async def gemini_translate(text: str, source_lang: str, target_lang: str) -> str:
    """Low-latency translation. Returns "" on miss so callers can fall back."""
    text = (text or "").strip()
    if not text:
        return ""
    src = _lang_name(source_lang)
    tgt = _lang_name(target_lang)
    system = (
        "You are a high-speed translator for a real-time Indian-bank branch caption. "
        "Translate the user's text accurately into the target language. "
        "Output ONLY the translation — no quotes, no notes, no preamble. "
        "Preserve numbers, ₹/INR amounts, account numbers and identifiers verbatim. "
        "Understand Indian banking terms (KYC, NEFT, RTGS, IMPS, UPI, FD, RD, IFSC). "
        "If the text is already in the target language, return it unchanged."
    )
    prompt = f"Translate from {src} to {tgt}:\n{text}"
    out = await _generate(prompt, system=system, max_tokens=512)
    return out.strip("`\"' \n")


async def gemini_json(
    *,
    system: str,
    user_prompt: str,
    schema_hint: str,
) -> dict[str, Any]:
    """Banking JSON completion via Gemini. Returns {} on any failure."""
    prompt = f"{schema_hint}\n\n{user_prompt}"
    raw = await _generate(prompt, system=system, json_mode=True, max_tokens=1024, timeout=12.0)
    if not raw:
        return {}
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception as e:  # noqa: BLE001
        logger.info("Gemini JSON parse failed: %s", e)
        return {}
