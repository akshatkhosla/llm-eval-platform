"""Background task for running evals and persisting results to the DB."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from evalplatform.core.runner import run_eval
from evalplatform.core.schemas import EvalConfig, SampleStatus
from evalplatform.db import repos
from evalplatform.db.models import ResultStatus, RunStatus
from evalplatform.tracing.instrumentor import Tracer

logger = logging.getLogger(__name__)

# Only one eval runs at a time; others wait in pending state until the slot is free.
# Lazily initialised on first use so it's always bound to the running event loop.
_queue_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _queue_semaphore
    if _queue_semaphore is None:
        _queue_semaphore = asyncio.Semaphore(1)
    return _queue_semaphore


async def run_eval_background(
    run_id: UUID,
    config: EvalConfig,
    session_factory: async_sessionmaker,
) -> None:
    """Execute an eval run end-to-end and persist all results.

    Updates run status throughout:
      pending → (queued wait) → running → completed (or failed on error)

    Only one eval runs at a time. While waiting for the slot the run stays in
    ``pending`` state so the UI shows it as queued.

    A :class:`~evalplatform.tracing.instrumentor.Tracer` is created for each
    run and the completed trace tree is stored in the ``trace_data`` column.
    """
    semaphore = _get_semaphore()

    # Block here until no other eval is running. Status stays "pending" in the
    # DB during this wait, which is exactly what we want to show in the UI.
    async with semaphore:
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
                        tokens_used=sample.tokens_used,
                        latency_ms=sample.latency_ms,
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

                total_tokens = sum(s.tokens_used for s in result.sample_results)
                total_latency_ms = sum(s.latency_ms for s in result.sample_results)
                passed = sum(1 for s in result.sample_results if s.status != SampleStatus.error)
                failed = sum(1 for s in result.sample_results if s.status == SampleStatus.error)

                await repos.update_run_progress(
                    session,
                    run_id,
                    total_samples=result.total_rows,
                    completed_samples=result.completed_rows,
                    passed_samples=passed,
                    failed_samples=failed,
                    aggregate_scores=aggregate_scores,
                    total_tokens=total_tokens,
                    total_latency_ms=total_latency_ms,
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
