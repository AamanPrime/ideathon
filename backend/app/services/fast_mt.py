"""Low-latency translation for live captions using Gemini.

Strategy (first hit wins):
  1. Configured Gemini API (via OpenAI-compatible endpoint).
  2. Offline demo phrasebook — guarantees the demo never goes silent.

Includes a small per-(source,target) cache so repeated partials don't re-call.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from google.genai import types

from app.config import get_settings
from app.services.demo_oracle import demo_translate
from app.services.vertex_client import get_vertex_client

logger = logging.getLogger(__name__)

# (source_lang, target_lang, text) -> (translated, ts). LRU-ish, bounded.
_cache: dict[tuple[str, str, str], tuple[str, float]] = {}
_CACHE_MAX = 256
_CACHE_TTL_S = 60.0


def _cache_get(key: tuple[str, str, str]) -> Optional[str]:
    item = _cache.get(key)
    if not item:
        return None
    value, ts = item
    if time.time() - ts > _CACHE_TTL_S:
        _cache.pop(key, None)
        return None
    return value


def _cache_put(key: tuple[str, str, str], value: str) -> None:
    if len(_cache) >= _CACHE_MAX:
        # Drop oldest entry (simple FIFO; cheap and good enough).
        oldest = min(_cache.items(), key=lambda kv: kv[1][1])[0]
        _cache.pop(oldest, None)
    _cache[key] = (value, time.time())


async def _llm_translate(text: str, source_lang: str, target_lang: str) -> str:
    """Tight Vertex AI-based translation using gemini-2.5-flash."""
    client = get_vertex_client()
    try:
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=json.dumps(
                {"source_lang": source_lang, "target_lang": target_lang, "text": text},
                ensure_ascii=False,
            ),
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=256,
                system_instruction=(
                    "You are a high-speed translator for a real-time banking caption."
                    " Translate the user's text from the source language to the target language."
                    " Output ONLY the translated text — no quotes, no preamble, no explanations."
                    " Preserve numbers, INR amounts (₹), account numbers and identifiers verbatim."
                    " If the input is already in the target language, return it unchanged."
                )
            )
        )
        out = (resp.text or "").strip()
        # Defensive: strip stray quotes/backticks the model sometimes emits.
        return out.strip("`\"' \n")
    except Exception as e:  # noqa: BLE001
        logger.warning("fast Vertex MT failed: %s", e)
        return text


async def detect_language(text: str) -> str:
    """Detects the ISO-639-1 language code (e.g. 'hi', 'gu', 'ta', 'en') of text using Vertex AI."""
    text = (text or "").strip()
    if not text:
        return "hi"  # Default fallback

    client = get_vertex_client()
    try:
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=text,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=10,
                system_instruction=(
                    "You are an expert language detector."
                    " Detect the language of the user's text and output ONLY its ISO 639-1 two-letter code (e.g., 'hi' for Hindi, 'gu' for Gujarati, 'ta' for Tamil, 'te' for Telugu, 'kn' for Kannada, 'ml' for Malayalam, 'mr' for Marathi, 'bn' for Bengali, 'pa' for Punjabi, 'or' for Odia, 'en' for English)."
                    " Output absolutely nothing else — no explanations, no quotes, just the two letter code."
                )
            )
        )
        out = (resp.text or "").strip().lower()
        out = out.strip("`\"' \n")
        if len(out) >= 2:
            return out[:2]
        return "hi"
    except Exception as e:  # noqa: BLE001
        logger.warning("Vertex language detection failed: %s", e)
        return "hi"



async def fast_translate(text: str, source_lang: str, target_lang: str) -> tuple[str, str]:
    """Translate `text` with the lowest available latency using Gemini.

    Returns (translated_text, engine_used) where engine ∈ {"gemini", "noop"}.
    Same-language pass-through is a no-op.
    """
    text = (text or "").strip()
    if not text:
        return "", "noop"
    if source_lang == target_lang:
        return text, "noop"

    key = (source_lang, target_lang, text)
    cached = _cache_get(key)
    if cached is not None:
        return cached, "cache"

    # Gemini-based translation
    translated = await _llm_translate(text, source_lang, target_lang)
    if translated and translated != text:
        _cache_put(key, translated)
        return translated, "gemini"

    # Offline phrasebook — guarantees demo never goes silent.
    demo = demo_translate(text, source_lang, target_lang)
    if demo and demo != text:
        _cache_put(key, demo)
        return demo, "demo"

    return text, "noop"
