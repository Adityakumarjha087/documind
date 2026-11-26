"""Evaluation runs (RAGAS-style metrics) per workspace."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.deps import AdminCtx, MemberCtx, SessionDep
from app.errors import NotFound
from app.models import EvalRun
from app.schemas import EvalRunIn, EvalRunOut
from app.services.jobs import enqueue_eval

router = APIRouter(prefix="/api/workspaces/{workspace_id}/evals", tags=["evaluation"])


@router.post("", response_model=EvalRunOut, status_code=status.HTTP_202_ACCEPTED)
async def create_eval(body: EvalRunIn, ctx: AdminCtx, session: SessionDep) -> EvalRun:
    run = EvalRun(
        workspace_id=ctx.workspace.id,
        name=body.name,
        status="running",
        config={"judge": body.judge, "questions": [q.model_dump() for q in body.questions]},
    )
    session.add(run)
    await session.commit()
    enqueue_eval(run.id)
    return run


@router.get("", response_model=list[EvalRunOut])
async def list_evals(ctx: MemberCtx, session: SessionDep) -> list[EvalRun]:
    rows = await session.execute(
        select(EvalRun)
        .where(EvalRun.workspace_id == ctx.workspace.id)
        .order_by(EvalRun.created_at.desc())
        .limit(50)
    )
    return list(rows.scalars())


@router.get("/{run_id}", response_model=EvalRunOut)
async def get_eval(run_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> EvalRun:
    run = await session.get(EvalRun, run_id)
    if run is None or run.workspace_id != ctx.workspace.id:
        raise NotFound("Evaluation run not found")
    return run
