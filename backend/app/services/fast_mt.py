"""Low-latency translation for live partial captions.

Strategy:
  1. Try Bhashini text translation (NMT, ~300-800ms) — same quality model as the final pipeline.
  2. Fall back to the configured LLM (Groq for sub-second latency on llama-3.x) with a tight prompt.
  3. If neither is configured, return the source text unchanged (caller can mark it as untranslated).

Includes a small per-(source,target) cache so repeated partials of the same prefix don't re-call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.services.bhashini_client import BhashiniError, bhashini

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
    """Tight LLM-based translation. Used as a fast fallback when Bhashini text NMT is unavailable.

    Groq's llama-3.x typically returns < 700ms for short text, which is the budget for a "live caption".
    """
    s = get_settings()
    api_key, base_url, model = s.llm_effective
    if not api_key or not model:
        return text

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    try:
        resp = await client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=256,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a high-speed translator for a real-time banking caption."
                        " Translate the user's text from the source language to the target language."
                        " Output ONLY the translated text — no quotes, no preamble, no explanations."
                        " Preserve numbers, INR amounts (₹), account numbers and identifiers verbatim."
                        " If the input is already in the target language, return it unchanged."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"source_lang": source_lang, "target_lang": target_lang, "text": text},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        out = (resp.choices[0].message.content or "").strip()
        # Defensive: strip stray quotes/backticks the model sometimes emits.
        return out.strip("`\"' \n")
    except Exception as e:  # noqa: BLE001
        logger.warning("fast LLM MT failed: %s", e)
        return text


async def fast_translate(text: str, source_lang: str, target_lang: str) -> tuple[str, str]:
    """Translate `text` with the lowest available latency.

    Returns (translated_text, engine_used) where engine ∈ {"bhashini", "llm", "noop"}.
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

    s = get_settings()
    has_bhashini = bool(s.bhashini_user_id and s.bhashini_ulca_api_key)

    # Try Bhashini first when configured — it's the same model the final result uses,
    # so the live caption matches the final translation more closely.
    if has_bhashini:
        try:
            translated = await asyncio.wait_for(
                bhashini.translate_text(source_lang=source_lang, target_lang=target_lang, text=text),
                timeout=2.5,
            )
            if translated and translated.strip():
                _cache_put(key, translated)
                return translated, "bhashini"
        except (BhashiniError, asyncio.TimeoutError) as e:
            logger.info("fast_translate: Bhashini fallback (%s)", e)

    # Fallback: LLM (Groq is the typical fast path here).
    translated = await _llm_translate(text, source_lang, target_lang)
    if translated and translated != text:
        _cache_put(key, translated)
        return translated, "llm"

    return text, "noop"
