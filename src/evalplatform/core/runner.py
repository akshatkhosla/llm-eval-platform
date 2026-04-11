"""Async eval runner: loads dataset, runs model + judges, returns results."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from contextlib import nullcontext
from pathlib import Path

from evalplatform.core.judges import (
    BaseJudge,
    ContainsKeywordJudge,
    LLMJudge,
    RegexMatchJudge,
)
from evalplatform.core.providers.factory import get_provider
from evalplatform.core.schemas import (
    AggregateScore,
    ContainsKeywordJudgeConfig,
    EvalConfig,
    EvalRunResult,
    JudgeResultStatus,
    LLMJudgeConfig,
    RegexMatchJudgeConfig,
    SampleResult,
    SampleStatus,
)

logger = logging.getLogger(__name__)

StatusCallback = Callable[[int, int], Coroutine[None, None, None]] | None


def _build_judges(config: EvalConfig) -> list[BaseJudge]:
    """Instantiate judge objects from the eval config."""
    judges: list[BaseJudge] = []
    for idx, jcfg in enumerate(config.judges):
        if isinstance(jcfg, LLMJudgeConfig):
            provider_name, model_name = jcfg.model.split("/", 1)
            provider_cfg = config.providers.get(provider_name)
            kwargs: dict[str, object] = {"model": model_name}
            if provider_cfg and provider_cfg.max_concurrency:
                kwargs["max_concurrency"] = provider_cfg.max_concurrency
            if provider_cfg and provider_cfg.base_url:
                kwargs["base_url"] = provider_cfg.base_url
            provider = get_provider(provider_name, model_name)
            judges.append(LLMJudge(provider=provider, rubric=jcfg.rubric, judge_index=idx))
        elif isinstance(jcfg, ContainsKeywordJudgeConfig):
            judges.append(
                ContainsKeywordJudge(
                    keyword=jcfg.keyword,
                    case_sensitive=jcfg.case_sensitive,
                    judge_index=idx,
                )
            )
        elif isinstance(jcfg, RegexMatchJudgeConfig):
            judges.append(RegexMatchJudge(pattern=jcfg.pattern, judge_index=idx))
    return judges


def _load_dataset(path: str | Path) -> list[dict[str, str]]:
    """Load a JSONL dataset, returning a list of row dicts."""
    rows: list[dict[str, str]] = []
    with Path(path).open() as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON at line %d", line_no)
                continue
            if "prompt" not in row:
                logger.warning("Skipping row at line %d: missing 'prompt' field", line_no)
                continue
            rows.append(row)
    return rows


async def _evaluate_sample(
    row_index: int,
    row: dict[str, str],
    provider_name: str,
    model_name: str,
    config: EvalConfig,
    judges: list[BaseJudge],
    semaphore: asyncio.Semaphore,
    tracer: object = None,
) -> SampleResult:
    """Run the target model and all judges for a single dataset row."""
    prompt = row["prompt"]
    expected = row.get("expected")
    metadata = {k: v for k, v in row.items() if k not in ("prompt", "expected")}

    sample_ctx = (
        tracer.span("sample_execution", sample_index=row_index)  # type: ignore[union-attr]
        if tracer is not None
        else nullcontext()
    )

    async with sample_ctx as sample_span:
        # Call the target model
        try:
            provider = get_provider(provider_name, model_name)
            provider_cfg = config.providers.get(provider_name)
            if provider_cfg and provider_cfg.base_url and hasattr(provider, "_base_url"):
                provider._base_url = provider_cfg.base_url  # noqa: SLF001

            llm_ctx = (
                tracer.span(  # type: ignore[union-attr]
                    "llm_call", provider=provider_name, model=model_name
                )
                if tracer is not None
                else nullcontext()
            )
            async with llm_ctx as llm_span:
                async with semaphore:
                    llm_resp = await provider.generate(
                        prompt=prompt,
                        system=None,
                        temperature=0.0,
                        max_tokens=1024,
                    )
                if llm_span is not None:
                    llm_span.attributes["input_tokens"] = llm_resp.input_tokens
                    llm_span.attributes["output_tokens"] = llm_resp.output_tokens
                    llm_span.attributes["latency_ms"] = llm_resp.latency_ms
                    llm_span.attributes["status"] = "ok"
            response_text = llm_resp.text

        except Exception as exc:
            logger.warning("Model call failed for row %d: %s", row_index, exc)
            if sample_span is not None:
                sample_span.attributes["status"] = "error"
            return SampleResult(
                row_index=row_index,
                prompt=prompt,
                expected=expected,
                status=SampleStatus.error,
                error=str(exc),
                metadata=metadata,
            )

        # Run all judges (each wrapped in its own span when tracing is active)
        async def _run_judge(j: BaseJudge) -> object:
            judge_ctx = (
                tracer.span(  # type: ignore[union-attr]
                    "judge_execution",
                    judge_index=j.judge_index,
                    judge_type=j.__class__.__name__,
                )
                if tracer is not None
                else nullcontext()
            )
            async with judge_ctx as judge_span:
                result = await j.judge(prompt, response_text, expected)
                if judge_span is not None:
                    judge_span.attributes["judge_score"] = result.score
                    judge_span.attributes["status"] = str(result.status)
            return result

        judge_results_raw = await asyncio.gather(
            *(_run_judge(j) for j in judges),
            return_exceptions=True,
        )

    from evalplatform.core.schemas import JudgeResult

    final_judge_results = []
    for jr in judge_results_raw:
        if isinstance(jr, Exception):
            final_judge_results.append(
                JudgeResult(
                    judge_type="unknown",
                    judge_index=-1,
                    status=JudgeResultStatus.error,
                    error=str(jr),
                )
            )
        else:
            final_judge_results.append(jr)

    has_errors = any(jr.status == JudgeResultStatus.error for jr in final_judge_results)
    status = SampleStatus.partial if has_errors else SampleStatus.passed

    if sample_span is not None:
        sample_span.attributes["status"] = str(status)

    return SampleResult(
        row_index=row_index,
        prompt=prompt,
        expected=expected,
        response=response_text,
        status=status,
        judge_results=final_judge_results,
        metadata=metadata,
    )


def _compute_aggregates(samples: list[SampleResult]) -> dict[int, AggregateScore]:
    """Compute per-judge aggregate scores across all samples."""
    # Collect scores by judge_index
    scores_by_judge: dict[int, list[int]] = {}
    for sample in samples:
        for jr in sample.judge_results:
            if jr.status == JudgeResultStatus.ok and jr.score is not None:
                scores_by_judge.setdefault(jr.judge_index, []).append(jr.score)

    aggregates: dict[int, AggregateScore] = {}
    for judge_idx, scores in scores_by_judge.items():
        aggregates[judge_idx] = AggregateScore(
            mean=sum(scores) / len(scores),
            min_score=min(scores),
            max_score=max(scores),
            count=len(scores),
        )
    return aggregates


async def run_eval(
    config: EvalConfig,
    status_callback: StatusCallback = None,
    tracer: object = None,
) -> EvalRunResult:
    """Execute an eval run end-to-end.

    Args:
        config: Validated eval configuration.
        status_callback: Optional async callable ``(completed, total) -> None``
            invoked after each sample finishes.
        tracer: Optional :class:`~evalplatform.tracing.instrumentor.Tracer` instance.
            When provided, the runner wraps each step in a named span.

    Returns:
        EvalRunResult with per-sample scores and aggregates.
    """
    provider_name, model_name = config.model.split("/", 1)
    judges = _build_judges(config)
    rows = _load_dataset(config.dataset)
    semaphore = asyncio.Semaphore(config.max_concurrency)

    root_ctx = (
        tracer.span("eval_run", provider=provider_name, model=model_name)  # type: ignore[union-attr]
        if tracer is not None
        else nullcontext()
    )

    sample_results: list[SampleResult] = []

    async with root_ctx:

        async def _run_one(idx: int, row: dict[str, str]) -> SampleResult:
            return await _evaluate_sample(
                row_index=idx,
                row=row,
                provider_name=provider_name,
                model_name=model_name,
                config=config,
                judges=judges,
                semaphore=semaphore,
                tracer=tracer,
            )

        tasks = [_run_one(idx, row) for idx, row in enumerate(rows)]
        for completed, coro in enumerate(asyncio.as_completed(tasks), 1):
            result = await coro
            sample_results.append(result)
            if status_callback is not None:
                await status_callback(completed, len(rows))

    # Sort by row_index for deterministic output
    sample_results.sort(key=lambda r: r.row_index)

    error_rows = sum(1 for r in sample_results if r.status == SampleStatus.error)
    aggregates = _compute_aggregates(sample_results)

    return EvalRunResult(
        total_rows=len(rows),
        completed_rows=len(sample_results),
        error_rows=error_rows,
        sample_results=sample_results,
        aggregate_scores=aggregates,
    )
