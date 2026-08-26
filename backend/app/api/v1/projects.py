"""
Project endpoints (docs/14 §8).

A project is the container research lives in. Deleting one deletes the research inside
it — sessions cascade at the DB level, and their LangGraph checkpoints are dropped
explicitly for the same reason session delete does it: those tables carry the full agent
state, including fetched page content, and are not reachable by a foreign key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.services import checkpoints

logger = structlog.get_logger()
router = APIRouter(prefix="/projects", tags=["Projects"])

DEFAULT_PROJECT_NAME = "General"


async def _counts(db: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Session counts for a page of projects — one GROUP BY, not one query per row."""
    if not project_ids:
        return {}
    rows = await db.execute(
        select(Session.project_id, func.count())
        .where(Session.project_id.in_(project_ids))
        .group_by(Session.project_id)
    )
    return {pid: n for pid, n in rows.all()}


def _to_response(project: Project, session_count: int = 0) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        archived_at=project.archived_at,
        created_at=project.created_at,
        session_count=session_count,
    )


async def get_or_create_default_project(db: AsyncSession, user_id: uuid.UUID) -> Project:
    """This user's fallback project, created on demand.

    New accounts have no projects, and a user must never be blocked from starting
    research just because they haven't made one. Mirrors the "General" project the
    backfill migration created for pre-existing accounts.
    """
    existing = (
        await db.execute(
            select(Project)
            .where(
                Project.user_id == user_id,
                func.lower(Project.name) == DEFAULT_PROJECT_NAME.lower(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    project = Project(user_id=user_id, name=DEFAULT_PROJECT_NAME)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def resolve_project(
    db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None
) -> Project:
    """The project a request targets: the one asked for, else the default."""
    if project_id is None:
        return await get_or_create_default_project(db, user_id)
    project = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    archived: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        (
            await db.execute(
                select(Project)
                .where(
                    Project.user_id == current_user.id,
                    Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None),
                )
                .order_by(Project.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    counts = await _counts(db, [p.id for p in rows])
    return ProjectListResponse(
        projects=[_to_response(p, counts.get(p.id, 0)) for p in rows],
        total=len(rows),
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    payload: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(user_id=current_user.id, name=payload.name, description=payload.description)
    db.add(project)
    try:
        await db.commit()
    except IntegrityError:
        # The unique index is case-insensitive, so this is the only reliable place to
        # detect a duplicate without racing a pre-check.
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"You already have a project named '{payload.name}'.",
        ) from None
    await db.refresh(project)
    logger.info("project_created", project_id=str(project.id))
    return _to_response(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await resolve_project(db, current_user.id, project_id)

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.archived is not None:
        project.archived_at = datetime.now(UTC) if payload.archived else None

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="You already have a project with that name."
        ) from None
    await db.refresh(project)
    counts = await _counts(db, [project.id])
    return _to_response(project, counts.get(project.id, 0))


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a project and every session in it.

    Refuses while any session is still running, for the same reason session delete
    does: pulling the row out from under an in-flight worker turns a clean failure
    into a confusing one.
    """
    project = await resolve_project(db, current_user.id, project_id)

    running = (
        await db.execute(
            select(func.count())
            .select_from(Session)
            .where(Session.project_id == project.id, Session.status == SessionStatus.RUNNING)
        )
    ).scalar_one()
    if running:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{running} session(s) in this project are still running.",
        )

    session_ids = (
        (await db.execute(select(Session.id).where(Session.project_id == project.id)))
        .scalars()
        .all()
    )

    await db.delete(project)  # sessions (and their logs/chat/audit) cascade
    await db.commit()

    for sid in session_ids:
        try:
            await checkpoints.delete_thread(str(sid))
        except Exception as e:  # noqa: BLE001 — user rows are gone; log and continue
            logger.warning("checkpoint_cleanup_failed", session_id=str(sid), error=str(e))

    # The project's corpus (docs/12 M10) is a standalone SQLite file keyed by project_id,
    # not reachable by the cascade above — no foreign key points at a path on disk. Left
    # alone, it becomes an orphan that never surfaces again (no route can address a
    # deleted project's corpus) while still holding every document and embedding that
    # was in it, contradicting the "no orphan vectors after a delete" standard the
    # project model itself documents (app/models/project.py).
    corpus_stem = settings.corpus_path / f"corpus_{project_id}"
    for suffix in (".sqlite", ".sqlite-wal", ".sqlite-shm"):
        path = corpus_stem.with_name(corpus_stem.name + suffix)
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("corpus_cleanup_failed", project_id=str(project_id), error=str(e))

    logger.info("project_deleted", project_id=str(project_id), sessions=len(session_ids))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
