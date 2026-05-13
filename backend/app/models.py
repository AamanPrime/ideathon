"""ORM models: User, DeskSessionRow, InteractionRecord, AuditEvent."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # role: admin | staff
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="staff")
    branch_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    preferred_lang: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sessions: Mapped[list["DeskSessionRow"]] = relationship(back_populates="user")


class DeskSessionRow(Base):
    __tablename__ = "desk_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # matches in-memory session_id (hex)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    customer_lang: Mapped[str] = mapped_column(String(8), nullable=False, default="hi")
    staff_lang: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | closed
    last_intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    form_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    turns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # redacted bilingual transcript
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[Optional["User"]] = relationship(back_populates="sessions")
    records: Mapped[list["InteractionRecord"]] = relationship(back_populates="session")


class InteractionRecord(Base):
    __tablename__ = "interaction_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("desk_sessions.id"), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    summary_staff_lang: Mapped[str] = mapped_column(Text, default="")
    summary_customer_lang: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["DeskSessionRow"] = relationship(back_populates="records")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
