"""Normalize INR amounts, dates, and account-style numbers for staff readout."""

from __future__ import annotations

import re
from typing import Any

INR_WORDS = re.compile(
    r"\b(?:rs\.?|rupees?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:lakh|lac|lacs|crore|cr)?\b",
    re.I,
)
PLAIN_INR = re.compile(r"₹\s*([\d,]+(?:\.\d+)?)\b")
ACCOUNT_LAST = re.compile(r"\b(?:account|a\/c|a\/c\.?)\s*(?:ending|no\.?|number)?\s*(\d{4})\b", re.I)


def normalize_financial_text(text: str) -> dict[str, Any]:
    """Return {normalized_snippets: [...], hints: [...]} for UI tiles."""
    if not text:
        return {"normalized_snippets": [], "hints": []}
    snippets: list[str] = []
    hints: list[str] = []

    for m in INR_WORDS.finditer(text):
        raw = m.group(0)
        snippets.append(f"Amount detected: {raw.strip()}")
    for m in PLAIN_INR.finditer(text):
        snippets.append(f"INR {m.group(1).replace(',', '')}")

    for m in ACCOUNT_LAST.finditer(text):
        hints.append(f"Account reference ends ••••{m.group(1)}")

    # ISO dates
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        hints.append(f"Date (ISO): {m.group(0)}")
    for m in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text):
        hints.append(f"Date (d/m/y): {m.group(0)}")

    return {"normalized_snippets": snippets[:8], "hints": hints[:8]}
