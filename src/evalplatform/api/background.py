"""Background task for running evals and persisting results to the DB."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from evalplatform.core.runner import run_eval
from evalplatform.core.schemas import EvalConfig, SampleStatus
from evalplatform.db import repos
from evalplatform.db.models import ResultStatus, RunStatus
from evalplatform.tracing.instrumentor import Tracer

logger = logging.getLogger(__name__)


async def run_eval_background(
    run_id: UUID,
    config: EvalConfig,
    session_factory: async_sessionmaker,
) -> None:
    """Execute an eval run end-to-end and persist all results.

    Updates run status throughout:
      pending → running → completed (or failed on error)

    A :class:`~evalplatform.tracing.instrumentor.Tracer` is created for each
    run and the completed trace tree is stored in the ``trace_data`` column.
    """
    async with session_factory() as session:
        await repos.update_run_status(session, run_id, RunStatus.running)

    async def _progress(completed: int, total: int) -> None:
        async with session_factory() as session:
            await repos.update_run_progress(
                session,
                run_id,
                total_samples=total,
                completed_samples=completed,
            )

    tracer = Tracer(run_id)

    try:
        result = await run_eval(config, status_callback=_progress, tracer=tracer)

        async with session_factory() as session:
            for sample in result.sample_results:
                judge_scores: dict[str, dict[str, object]] = {
                    str(jr.judge_index): {
                        "score": jr.score,
                        "reasoning": jr.reasoning,
                        "status": str(jr.status),
                        "judge_type": jr.judge_type,
                        "error": jr.error,
                    }
                    for jr in sample.judge_results
                }
                row_status = (
                    ResultStatus.error
                    if sample.status == SampleStatus.error
                    else ResultStatus.success
                )
                await repos.save_result(
                    session,
                    run_id=run_id,
                    sample_index=sample.row_index,
                    input_text=sample.prompt,
                    status=row_status,
                    model_output=sample.response,
                    expected_output=sample.expected,
                    judge_scores=judge_scores,
                    error_message=sample.error,
                )

            aggregate_scores: dict[str, object] = {
                str(judge_idx): {
                    "mean": agg.mean,
                    "min_score": agg.min_score,
                    "max_score": agg.max_score,
                    "count": agg.count,
                }
                for judge_idx, agg in result.aggregate_scores.items()
            }

            await repos.update_run_progress(
                session,
                run_id,
                total_samples=result.total_rows,
                completed_samples=result.completed_rows,
                aggregate_scores=aggregate_scores,
            )
            await repos.update_run_status(session, run_id, RunStatus.completed)

        # Persist the trace tree
        try:
            trace = tracer.build_trace()
            async with session_factory() as session:
                await repos.save_trace(
                    session,
                    run_id,
                    trace.model_dump(mode="json"),
                )
        except Exception:
            logger.exception("Failed to save trace for run %s", run_id)

    except Exception as exc:
        logger.exception("Eval run %s failed", run_id)
        async with session_factory() as session:
            await repos.update_run_status(
                session,
                run_id,
                RunStatus.failed,
                error_message=str(exc),
            )
