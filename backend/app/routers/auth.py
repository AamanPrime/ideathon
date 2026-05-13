"""Auth router: register (admin-only), login, /me."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, get_current_user, hash_password, require_role, verify_password
from app.db import get_db
from app.models import AuditEvent, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""
    role: str = "staff"
    branch_code: str = ""
    preferred_lang: str = "en"


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    branch_code: str
    preferred_lang: str

    @classmethod
    def from_user(cls, u: User) -> "UserOut":
        return cls(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            branch_code=u.branch_code,
            preferred_lang=u.preferred_lang,
        )


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    token = create_access_token(subject=user.id, role=user.role, extra={"email": user.email})
    db.add(AuditEvent(user_id=user.id, event="login", payload={"email": user.email}))
    await db.commit()
    return TokenOut(access_token=token, user=UserOut.from_user(user).model_dump())


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.from_user(user)


@router.post("/register", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)) -> UserOut:
    email = body.email.lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="email_in_use")
    if body.role not in ("admin", "staff"):
        raise HTTPException(status_code=400, detail="invalid_role")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        branch_code=body.branch_code,
        preferred_lang=body.preferred_lang,
    )
    db.add(user)
    db.add(AuditEvent(user_id=user.id, event="user_registered", payload={"email": email, "role": body.role}))
    await db.commit()
    await db.refresh(user)
    return UserOut.from_user(user)


# --- Bootstrap helper used at startup ---
async def ensure_seed_admin(db: AsyncSession, *, email: str, password: str, name: str) -> Optional[User]:
    """Create the first admin if no users exist yet."""
    count = (await db.execute(select(User))).scalars().first()
    if count:
        return None
    admin = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=name,
        role="admin",
        branch_code="HQ",
        preferred_lang="en",
    )
    db.add(admin)
    db.add(AuditEvent(user_id=admin.id, event="seed_admin_created", payload={"email": email}))
    await db.commit()
    return admin
