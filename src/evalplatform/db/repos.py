"""Repository layer — all database access lives here."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evalplatform.db.models import EvalResult, EvalRun, RunStatus


async def create_run(
    session: AsyncSession,
    *,
    name: str,
    config_yaml: str,
    provider: str,
    model: str,
) -> EvalRun:
    """Insert a new EvalRun in pending status and return it."""
    run = EvalRun(
        name=name,
        config_yaml=config_yaml,
        provider=provider,
        model=model,
        status=RunStatus.pending,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> EvalRun | None:
    """Return the EvalRun with the given id, or None if not found."""
    result = await session.execute(select(EvalRun).where(EvalRun.id == run_id))
    return result.scalar_one_or_none()


async def list_runs(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[EvalRun]:
    """Return EvalRuns ordered by creation time, newest first.

    Optionally filter by status and paginate with limit/offset.
    """
    stmt = select(EvalRun).order_by(EvalRun.created_at.desc())
    if status is not None:
        stmt = stmt.where(EvalRun.status == status)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return result.scalars().all()


async def update_run_status(
    session: AsyncSession,
    run_id: uuid.UUID,
    status: RunStatus,
    *,
    error_message: str | None = None,
) -> EvalRun:
    """Update the status of a run, setting timestamps as appropriate."""
    run = await get_run(session, run_id)
    if run is None:
        raise ValueError(f"EvalRun {run_id} not found")
    run.status = status
    if status == RunStatus.running and run.started_at is None:
        run.started_at = datetime.now(UTC)
    if status in (RunStatus.completed, RunStatus.failed):
        run.completed_at = datetime.now(UTC)
    if error_message is not None:
        run.error_message = error_message
    await session.commit()
    await session.refresh(run)
    return run


async def update_run_progress(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    total_samples: int | None = None,
    completed_samples: int | None = None,
    passed_samples: int | None = None,
    failed_samples: int | None = None,
    aggregate_scores: dict[str, float] | None = None,
    total_tokens: int | None = None,
    total_latency_ms: float | None = None,
) -> EvalRun:
    """Update counters and aggregate scores on a run."""
    run = await get_run(session, run_id)
    if run is None:
        raise ValueError(f"EvalRun {run_id} not found")
    if total_samples is not None:
        run.total_samples = total_samples
    if completed_samples is not None:
        run.completed_samples = completed_samples
    if passed_samples is not None:
        run.passed_samples = passed_samples
    if failed_samples is not None:
        run.failed_samples = failed_samples
    if aggregate_scores is not None:
        run.aggregate_scores = aggregate_scores
    if total_tokens is not None:
        run.total_tokens = total_tokens
    if total_latency_ms is not None:
        run.total_latency_ms = total_latency_ms
    await session.commit()
    await session.refresh(run)
    return run


async def save_result(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    sample_index: int,
    input_text: str,
    status: str,
    model_output: str | None = None,
    expected_output: str | None = None,
    judge_scores: dict[str, dict[str, object]] | None = None,
    tokens_used: int = 0,
    latency_ms: float = 0.0,
    error_message: str | None = None,
) -> EvalResult:
    """Insert a new EvalResult row and return it."""
    result = EvalResult(
        run_id=run_id,
        sample_index=sample_index,
        input_text=input_text,
        model_output=model_output,
        expected_output=expected_output,
        judge_scores=judge_scores if judge_scores is not None else {},
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        status=status,
        error_message=error_message,
    )
    session.add(result)
    await session.commit()
    await session.refresh(result)
    return result


async def get_results_for_run(session: AsyncSession, run_id: uuid.UUID) -> Sequence[EvalResult]:
    """Return all EvalResults for a run ordered by sample_index."""
    result = await session.execute(
        select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.sample_index)
    )
    return result.scalars().all()


async def save_trace(
    session: AsyncSession,
    run_id: uuid.UUID,
    trace_data: dict[str, object],
) -> EvalRun:
    """Persist a serialised EvalTrace dict into the trace_data column of a run."""
    run = await get_run(session, run_id)
    if run is None:
        raise ValueError(f"EvalRun {run_id} not found")
    run.trace_data = trace_data
    await session.commit()
    await session.refresh(run)
    return run


async def get_trace(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> dict[str, object] | None:
    """Return the raw trace_data dict for a run, or None if not yet stored."""
    run = await get_run(session, run_id)
    if run is None:
        return None
    return run.trace_data  # type: ignore[return-value]


async def delete_run(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Delete an EvalRun (cascades to results). Returns True if found and deleted."""
    run = await get_run(session, run_id)
    if run is None:
        return False
    await session.delete(run)
    await session.commit()
    return True


async def get_results_for_runs(
    session: AsyncSession,
    run_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Sequence[EvalResult]]:
    """Return results grouped by run_id for multiple runs at once."""
    stmt = (
        select(EvalResult)
        .where(EvalResult.run_id.in_(run_ids))
        .order_by(EvalResult.run_id, EvalResult.sample_index)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Group results by run_id
    grouped: dict[uuid.UUID, list[EvalResult]] = {rid: [] for rid in run_ids}
    for row in rows:
        grouped[row.run_id].append(row)

    return grouped
