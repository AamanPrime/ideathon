"""Low-latency translation for live captions.

Strategy (first hit wins):
  1. Bhashini ULCA NMT — when credentials are configured (production path).
  2. MyMemory public translation API — no key required, generous free tier,
     covers all Indic↔English pairs we need.
  3. Configured LLM (Groq for sub-second latency on llama-3.x) — last resort
     when MyMemory throttles or errors.
  4. Offline demo phrasebook — guarantees the demo never goes silent.

Includes a small per-(source,target) cache so repeated partials don't re-call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.services.bhashini_client import BhashiniError, bhashini
from app.services.demo_oracle import demo_translate

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


async def _mymemory_translate(text: str, source_lang: str, target_lang: str) -> str:
    """Public free translation API — no auth required.

    Quota is 5000 chars/day/IP (50k with a contact email). For a branch desk
    demo this is essentially unlimited. Returns empty string on error so the
    caller can fall back to the next layer.
    """
    if not text:
        return ""
    pair = f"{source_lang}|{target_lang}"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": pair},
            )
            if r.status_code >= 400:
                return ""
            data = r.json()
        if int(data.get("responseStatus", 0)) != 200:
            return ""
        translated = (data.get("responseData") or {}).get("translatedText") or ""
        translated = translated.strip()
        # MyMemory occasionally echoes the source verbatim when it can't
        # translate — treat that as a miss.
        if not translated or translated.strip().lower() == text.strip().lower():
            return ""
        # Some responses prepend "MYMEMORY WARNING" — drop those.
        if translated.upper().startswith("MYMEMORY WARNING"):
            return ""
        return translated
    except Exception as e:  # noqa: BLE001
        logger.info("MyMemory translate failed: %s", e)
        return ""


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

    # 1. Bhashini first when configured (matches the production pipeline).
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

    # 2. MyMemory public API — real translation, no key needed.
    translated = await _mymemory_translate(text, source_lang, target_lang)
    if translated and translated != text:
        _cache_put(key, translated)
        return translated, "mymemory"

    # 3. Configured LLM (Groq / OpenAI-compatible).
    translated = await _llm_translate(text, source_lang, target_lang)
    if translated and translated != text:
        _cache_put(key, translated)
        return translated, "llm"

    # 4. Offline phrasebook — guarantees demo never goes silent.
    demo = demo_translate(text, source_lang, target_lang)
    if demo and demo != text:
        _cache_put(key, demo)
        return demo, "demo"

    return text, "noop"
