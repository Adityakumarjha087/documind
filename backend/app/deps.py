"""FastAPI dependencies: DB session, current user, workspace RBAC."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import Forbidden, NotFound, Unauthorized
from app.models import ROLE_RANK, Membership, Role, User, Workspace
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if creds is None:
        raise Unauthorized("Missing bearer token")
    try:
        user_id = decode_access_token(creds.credentials)
    except (jwt.PyJWTError, ValueError, KeyError) as e:
        raise Unauthorized("Invalid or expired token") from e
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass
class WorkspaceContext:
    workspace: Workspace
    role: Role
    user: User


def require_role(minimum: Role) -> Callable[..., Coroutine[Any, Any, WorkspaceContext]]:
    async def dep(
        session: SessionDep,
        user: CurrentUser,
        workspace_id: Annotated[uuid.UUID, Path()],
    ) -> WorkspaceContext:
        row = (
            await session.execute(
                select(Workspace, Membership.role)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(Workspace.id == workspace_id, Membership.user_id == user.id)
            )
        ).first()
        if row is None:
            # 404 rather than 403 so workspace ids can't be probed.
            raise NotFound("Workspace not found")
        ws, role = row
        if ROLE_RANK[role] < ROLE_RANK[minimum]:
            raise Forbidden(f"Requires {minimum.value} role")
        return WorkspaceContext(ws, role, user)

    return dep


MemberCtx = Annotated[WorkspaceContext, Depends(require_role(Role.member))]
AdminCtx = Annotated[WorkspaceContext, Depends(require_role(Role.admin))]
OwnerCtx = Annotated[WorkspaceContext, Depends(require_role(Role.owner))]
