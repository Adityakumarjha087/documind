"""Registration, login, refresh-token rotation (with reuse detection), logout."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import select, update

from app.config import get_settings
from app.deps import CurrentUser, SessionDep
from app.errors import Conflict, Unauthorized
from app.models import Membership, RefreshToken, Role, User, Workspace
from app.schemas import LoginIn, RefreshIn, RegisterIn, TokenPair, UserOut
from app.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def _issue(session: SessionDep, user: User, family: uuid.UUID | None = None) -> TokenPair:
    s = get_settings()
    raw, digest = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            family_id=family or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days),
        )
    )
    await session.commit()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=raw,
        expires_in=s.access_token_minutes * 60,
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, session: SessionDep) -> TokenPair:
    email = body.email.lower()
    if (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise Conflict("An account with this email already exists")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password))
    ws = Workspace(name=body.workspace_name or f"{body.full_name.split()[0]}'s workspace")
    session.add_all([user, ws])
    await session.flush()
    session.add(Membership(user_id=user.id, workspace_id=ws.id, role=Role.owner))
    return await _issue(session, user)


@router.post("/login", response_model=TokenPair)
async def login(body: LoginIn, session: SessionDep) -> TokenPair:
    user = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        raise Unauthorized("Invalid email or password")
    return await _issue(session, user)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, session: SessionDep) -> TokenPair:
    token = (
        await session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(body.refresh_token)
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if token is None:
        raise Unauthorized("Invalid refresh token")
    if token.revoked_at is not None:
        # Reuse of a rotated token → likely theft: revoke the whole family.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        raise Unauthorized("Refresh token reuse detected; please log in again")
    if token.expires_at < now:
        raise Unauthorized("Refresh token expired")
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("User inactive")
    token.revoked_at = now
    return await _issue(session, user, family=token.family_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshIn, session: SessionDep) -> None:
    token = (
        await session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(body.refresh_token)
            )
        )
    ).scalar_one_or_none()
    if token is not None and token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        await session.commit()


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
