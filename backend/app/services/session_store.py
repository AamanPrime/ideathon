from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field, fields
from typing import Any


@dataclass
class ConversationTurn:
    role: str  # "customer" | "staff"
    source_lang: str
    text_original: str
    text_translated: str
    confidence: float | None = None  # ASR / segment confidence when available
    ts: float = field(default_factory=time.time)


@dataclass
class SessionMetrics:
    customer_turns: int = 0
    staff_turns: int = 0
    low_confidence_segments: int = 0
    bhashini_errors: int = 0
    tts_playouts: int = 0


@dataclass
class FormSnapshot:
    full_name: str | None = None
    date_of_birth: str | None = None
    address: str | None = None
    pan: str | None = None
    aadhaar: str | None = None
    phone: str | None = None
    email: str | None = None

    def merge(self, other: dict[str, Any]) -> None:
        allowed = {f.name for f in fields(self)}
        for k, v in other.items():
            if k not in allowed or v is None or v == "":
                continue
            current = getattr(self, k)
            if current in (None, "") or len(str(v)) > len(str(current or "")):
                setattr(self, k, v)


@dataclass
class DeskSession:
    """In-memory only — no institutional memory (nothing persisted across restarts or sessions)."""

    session_id: str
    ws: Any | None = None
    created_at: float = field(default_factory=time.time)
    customer_lang: str = "hi"
    staff_lang: str = "en"
    turns: list[ConversationTurn] = field(default_factory=list)
    form: FormSnapshot = field(default_factory=FormSnapshot)
    last_intent: str | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)
    metrics: SessionMetrics = field(default_factory=SessionMetrics)

    def log_audit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        self.audit.append({"ts": time.time(), "event": event, "payload": payload or {}})

    def duration_sec(self) -> float:
        return max(0.0, time.time() - self.created_at)

    def snapshot_metrics(self) -> dict[str, Any]:
        d = self.duration_sec()
        turns = len(self.turns)
        return {
            "session_seconds": round(d, 1),
            "total_turns": turns,
            "customer_turns": self.metrics.customer_turns,
            "staff_turns": self.metrics.staff_turns,
            "low_confidence_segments": self.metrics.low_confidence_segments,
            "bhashini_errors": self.metrics.bhashini_errors,
            "tts_playouts": self.metrics.tts_playouts,
            "approx_handling_index": round(turns / max(d / 60.0, 0.01), 2),
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, DeskSession] = {}

    def new_session(self, customer_lang: str, staff_lang: str) -> DeskSession:
        sid = uuid.uuid4().hex
        sess = DeskSession(session_id=sid, customer_lang=customer_lang, staff_lang=staff_lang)
        self._sessions[sid] = sess
        return sess

    def get(self, session_id: str) -> DeskSession | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


store = SessionStore()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
