"""Prompt-injection hardening and PII redaction for UI/export."""

from __future__ import annotations

import re
from typing import Any

_INJECTION_PATTERNS = (
    r"ignore (all )?(previous|prior) instructions",
    r"disregard (the )?system prompt",
    r"you are now",
    r"jailbreak",
    r"developer mode",
    r"<\|.*\|>",
)


def sanitize_for_llm(text: str, *, max_chars: int = 12000) -> str:
    """Strip common jailbreak prefaces; truncate. Does not remove legitimate banking words."""
    t = (text or "").strip()
    if len(t) > max_chars:
        t = t[:max_chars] + "\n[truncated]"
    lower = t.lower()
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, lower, re.I):
            t = "[sanitized: instruction-like pattern removed]\n" + re.sub(pat, " ", t, flags=re.I)
    return t


def redact_pii_display(text: str) -> str:
    """Mask PAN, phone, email, 12-digit Aadhaar for staff 'privacy display' mode."""
    if not text:
        return text
    t = text
    t = re.sub(r"\b\d{4}\s?\d{4}\s?\d{4}\b", "XXXX-XXXX-####", t)
    t = re.sub(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "XXXXX####X", t, flags=re.I)
    t = re.sub(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b", "+91-XXXXXX####", t)
    t = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", "***@***", t, flags=re.I)
    return t


def redact_mapping(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact_pii_display(obj)
    if isinstance(obj, list):
        return [redact_mapping(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_mapping(v) for k, v in obj.items()}
    return obj
