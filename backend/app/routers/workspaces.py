"""Workspaces and membership management (owner/admin/member RBAC)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.deps import AdminCtx, CurrentUser, MemberCtx, OwnerCtx, SessionDep
from app.errors import Conflict, Forbidden, NotFound
from app.models import Membership, Role, User, Workspace
from app.schemas import MemberIn, MemberOut, MemberUpdate, WorkspaceIn, WorkspaceOut

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(user: CurrentUser, session: SessionDep) -> list[WorkspaceOut]:
    rows = await session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.created_at)
    )
    return [WorkspaceOut(id=w.id, name=w.name, role=r, created_at=w.created_at) for w, r in rows]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceIn, user: CurrentUser, session: SessionDep
) -> WorkspaceOut:
    ws = Workspace(name=body.name)
    session.add(ws)
    await session.flush()
    session.add(Membership(user_id=user.id, workspace_id=ws.id, role=Role.owner))
    await session.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, role=Role.owner, created_at=ws.created_at)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(ctx: MemberCtx) -> WorkspaceOut:
    w = ctx.workspace
    return WorkspaceOut(id=w.id, name=w.name, role=ctx.role, created_at=w.created_at)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def rename_workspace(body: WorkspaceIn, ctx: AdminCtx, session: SessionDep) -> WorkspaceOut:
    ws = await session.get(Workspace, ctx.workspace.id)
    assert ws is not None
    ws.name = body.name
    await session.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, role=ctx.role, created_at=ws.created_at)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(ctx: OwnerCtx, session: SessionDep) -> None:
    ws = await session.get(Workspace, ctx.workspace.id)
    await session.delete(ws)
    await session.commit()


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(ctx: MemberCtx, session: SessionDep) -> list[MemberOut]:
    rows = await session.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == ctx.workspace.id)
        .order_by(User.full_name)
    )
    return [MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=r) for u, r in rows]


@router.post("/{workspace_id}/members", response_model=MemberOut, status_code=201)
async def add_member(body: MemberIn, ctx: AdminCtx, session: SessionDep) -> MemberOut:
    if body.role == Role.owner and ctx.role != Role.owner:
        raise Forbidden("Only owners can add owners")
    user = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("No registered user with that email")
    exists = await session.execute(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == ctx.workspace.id
        )
    )
    if exists.scalar_one_or_none():
        raise Conflict("User is already a member")
    session.add(Membership(user_id=user.id, workspace_id=ctx.workspace.id, role=body.role))
    await session.commit()
    return MemberOut(user_id=user.id, email=user.email, full_name=user.full_name, role=body.role)


async def _membership(session: SessionDep, ws_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    m = (
        await session.execute(
            select(Membership).where(
                Membership.workspace_id == ws_id, Membership.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise NotFound("Member not found")
    return m


async def _owner_count(session: SessionDep, ws_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).where(
                Membership.workspace_id == ws_id, Membership.role == Role.owner
            )
        )
        or 0
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: uuid.UUID, body: MemberUpdate, ctx: AdminCtx, session: SessionDep
) -> MemberOut:
    m = await _membership(session, ctx.workspace.id, user_id)
    if Role.owner in (m.role, body.role) and ctx.role != Role.owner:
        raise Forbidden("Only owners can change owner roles")
    if (
        m.role == Role.owner
        and body.role != Role.owner
        and await _owner_count(session, ctx.workspace.id) <= 1
    ):
        raise Conflict("A workspace must keep at least one owner")
    m.role = body.role
    await session.commit()
    user = await session.get(User, user_id)
    assert user is not None
    return MemberOut(user_id=user.id, email=user.email, full_name=user.full_name, role=m.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> None:
    m = await _membership(session, ctx.workspace.id, user_id)
    is_self = user_id == ctx.user.id
    if not is_self and ctx.role == Role.member:
        raise Forbidden("Requires admin role")
    if m.role == Role.owner and ctx.role != Role.owner:
        raise Forbidden("Only owners can remove owners")
    if m.role == Role.owner and await _owner_count(session, ctx.workspace.id) <= 1:
        raise Conflict("A workspace must keep at least one owner")
    await session.delete(m)
    await session.commit()
