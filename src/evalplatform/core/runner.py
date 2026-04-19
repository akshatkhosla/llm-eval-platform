"""Async eval runner: loads dataset, runs model + judges, returns results."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from evalplatform.core.judges import (
    BaseJudge,
    CoherenceJudge,
    ContainsKeywordJudge,
    FaithfulnessJudge,
    LLMJudge,
    RegexMatchJudge,
    RelevanceJudge,
)
from evalplatform.core.providers.factory import get_provider
from evalplatform.core.schemas import (
    AggregateScore,
    CoherenceJudgeConfig,
    ContainsKeywordJudgeConfig,
    EvalConfig,
    EvalRunResult,
    FaithfulnessJudgeConfig,
    JudgeResultStatus,
    LLMJudgeConfig,
    RegexMatchJudgeConfig,
    RelevanceJudgeConfig,
    SampleResult,
    SampleStatus,
)
from evalplatform.core.settings import settings

if TYPE_CHECKING:
    from evalplatform.tracing.instrumentor import Tracer

logger = logging.getLogger(__name__)

# Type alias for the optional progress-reporting callback.
# It receives (completed_count, total_count) and is awaited after each sample finishes.
StatusCallback = Callable[[int, int], Coroutine[None, None, None]] | None


def _build_judges(config: EvalConfig) -> list[BaseJudge]:
    """Instantiate judge objects from the eval config.

    Reads the `judges` list in the config and creates the correct judge class
    for each entry. Think of this like hiring a panel of reviewers — each judge
    has a different specialty (LLM grading, keyword detection, regex, etc.).

    For LLM-based judges (LLMJudge, FaithfulnessJudge, RelevanceJudge,
    CoherenceJudge) the model string is in "provider/model" format, so we
    split it and ask the factory for the right provider object.

    Args:
        config: Validated eval configuration containing the judges list
                and provider settings.

    Returns:
        A list of instantiated judge objects ready to score LLM responses.
    """
    judges: list[BaseJudge] = []
    for idx, jcfg in enumerate(config.judges):
        if isinstance(jcfg, LLMJudgeConfig):
            # Split "gemini/gemini-2.5-flash" → provider="gemini", model="gemini-2.5-flash"
            provider_name, model_name = jcfg.model.split("/", 1)
            provider_cfg = config.providers.get(provider_name)
            kwargs: dict[str, object] = {"model": model_name}
            # Pass optional provider-level settings (concurrency cap, custom base URL)
            if provider_cfg and provider_cfg.max_concurrency:
                kwargs["max_concurrency"] = provider_cfg.max_concurrency
            if provider_cfg and provider_cfg.base_url:
                kwargs["base_url"] = provider_cfg.base_url
            provider = get_provider(provider_name, model_name)
            judges.append(LLMJudge(provider=provider, rubric=jcfg.rubric, judge_index=idx))
        elif isinstance(jcfg, ContainsKeywordJudgeConfig):
            # Simple rule-based judge: checks if a keyword appears in the response
            judges.append(
                ContainsKeywordJudge(
                    keyword=jcfg.keyword,
                    case_sensitive=jcfg.case_sensitive,
                    judge_index=idx,
                )
            )
        elif isinstance(jcfg, RegexMatchJudgeConfig):
            # Rule-based judge: checks if a regex pattern matches the response
            judges.append(RegexMatchJudge(pattern=jcfg.pattern, judge_index=idx))
        elif isinstance(jcfg, FaithfulnessJudgeConfig):
            # LLM judge: scores whether the response is grounded in the source material
            provider_name, model_name = jcfg.model.split("/", 1)
            provider = get_provider(provider_name, model_name)
            judges.append(FaithfulnessJudge(provider=provider, judge_index=idx))
        elif isinstance(jcfg, RelevanceJudgeConfig):
            # LLM judge: scores whether the response actually addresses the question
            provider_name, model_name = jcfg.model.split("/", 1)
            provider = get_provider(provider_name, model_name)
            judges.append(RelevanceJudge(provider=provider, judge_index=idx))
        elif isinstance(jcfg, CoherenceJudgeConfig):
            # LLM judge: scores whether the response is logically structured
            provider_name, model_name = jcfg.model.split("/", 1)
            provider = get_provider(provider_name, model_name)
            judges.append(CoherenceJudge(provider=provider, judge_index=idx))
        else:
            raise ValueError(
                f"Unhandled judge config type {type(jcfg).__name__!r} at index {idx}. "
                "Update _build_judges to handle this judge type."
            )
    return judges


def _load_dataset(path: str | Path) -> list[dict[str, str]]:
    """Load a JSONL dataset, returning a list of row dicts.

    Reads the file line by line (JSONL = one JSON object per line). Skips blank
    lines and any line that isn't valid JSON. Also skips rows that are missing
    the required "prompt" field, since we can't evaluate without an input.

    Raises ValueError if the resolved path escapes the configured DATASET_ROOT,
    preventing path traversal attacks via user-supplied config.

    Args:
        path: File path to a `.jsonl` file. Each line must be a JSON object
              with at least a "prompt" key. An optional "expected" key holds
              the ground-truth answer for judges that need it.

    Returns:
        A list of row dicts. Each dict has at minimum {"prompt": "..."} and
        optionally {"expected": "..."} plus any extra metadata fields.
    """
    resolved = Path(path).resolve()
    dataset_root = Path(settings.dataset_root).resolve()
    if not str(resolved).startswith(str(dataset_root) + "/") and resolved != dataset_root:
        raise ValueError(
            f"Dataset path {str(path)!r} resolves to {resolved}, which is outside "
            f"the allowed dataset root {dataset_root}. Set DATASET_ROOT to expand this."
        )

    rows: list[dict[str, str]] = []
    with resolved.open() as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                # Skip blank lines silently
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
    tracer: Tracer | None = None,
) -> SampleResult:
    """Run the target model and all judges for a single dataset row.

    This is the core unit of work. For each row we:
      1. Call the target LLM to generate a response (gated by the semaphore
         to respect max_concurrency).
      2. Run all judges in parallel on that response (via asyncio.gather).
      3. Collect results, converting any judge exceptions into error JudgeResults.
      4. Return a SampleResult with status "passed" or "partial" (if any judge
         errored) or "error" (if the LLM call itself failed).

    When a `tracer` is provided, each step is wrapped in a named span so the
    full timing tree is captured:
        sample_execution
          └── llm_call
          └── judge_execution (one per judge)

    Args:
        row_index:     Zero-based index of this row in the dataset (used for ordering).
        row:           The raw dataset row dict with "prompt" and optional "expected".
        provider_name: Name of the LLM provider (e.g. "gemini", "ollama").
        model_name:    Model identifier understood by the provider (e.g. "gemini-2.5-flash").
        config:        Full eval config (used to look up provider base_url overrides).
        judges:        Pre-built list of judge objects to run on the response.
        semaphore:     Shared asyncio.Semaphore that caps concurrent LLM calls.
        tracer:        Optional Tracer instance; if None, no spans are recorded.

    Returns:
        SampleResult containing the prompt, model response, all judge scores,
        and an overall status.
    """
    prompt = row["prompt"]
    expected = row.get("expected")
    # Carry along any extra fields (e.g. "category", "source") as metadata
    metadata = {k: v for k, v in row.items() if k not in ("prompt", "expected")}

    # Wrap the whole sample in a span when tracing is active; otherwise use a no-op context
    sample_ctx = (
        tracer.span("sample_execution", sample_index=row_index)
        if tracer is not None
        else nullcontext()
    )

    async with sample_ctx as sample_span:
        # ── Step 1: Call the target LLM ──────────────────────────────────────
        try:
            provider = get_provider(provider_name, model_name)
            provider_cfg = config.providers.get(provider_name)
            # Apply a custom base_url if configured (e.g. for self-hosted Ollama)
            if provider_cfg and provider_cfg.base_url and hasattr(provider, "_base_url"):
                provider._base_url = provider_cfg.base_url  # noqa: SLF001

            # Wrap the LLM call in its own span to capture token counts and latency
            llm_ctx = (
                tracer.span("llm_call", provider=provider_name, model=model_name)
                if tracer is not None
                else nullcontext()
            )
            async with llm_ctx as llm_span:
                # The semaphore ensures we never exceed max_concurrency simultaneous
                # LLM calls — important for rate-limit-sensitive providers like Gemini.
                async with semaphore:
                    llm_resp = await provider.generate(
                        prompt=prompt,
                        system=None,
                        temperature=0.0,  # Deterministic output for reproducibility
                        max_tokens=1024,
                    )
                # Record token/latency metrics into the span attributes
                if llm_span is not None:
                    llm_span.attributes["input_tokens"] = llm_resp.input_tokens
                    llm_span.attributes["output_tokens"] = llm_resp.output_tokens
                    llm_span.attributes["latency_ms"] = llm_resp.latency_ms
                    llm_span.attributes["status"] = "ok"
            response_text = llm_resp.text
            resp_tokens = llm_resp.input_tokens + llm_resp.output_tokens
            resp_latency_ms = llm_resp.latency_ms

        except Exception as exc:
            # If the LLM call fails entirely, return an error SampleResult immediately.
            # Judges cannot run without a response, so we short-circuit here.
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

        # ── Step 2: Run all judges in parallel ───────────────────────────────
        async def _run_judge(j: BaseJudge) -> object:
            """Invoke a single judge and record a span around it."""
            judge_ctx = (
                tracer.span(
                    "judge_execution",
                    judge_index=j.judge_index,
                    judge_type=j.__class__.__name__,
                )
                if tracer is not None
                else nullcontext()
            )
            async with judge_ctx as judge_span:
                result = await j.judge(prompt, response_text, expected)
                # Persist score and status into the span so the trace UI shows them
                if judge_span is not None:
                    judge_span.attributes["judge_score"] = result.score
                    judge_span.attributes["status"] = str(result.status)
            return result

        # asyncio.gather runs all judges concurrently. return_exceptions=True means
        # a crashing judge doesn't cancel the others — we handle errors below.
        judge_results_raw = await asyncio.gather(
            *(_run_judge(j) for j in judges),
            return_exceptions=True,
        )

    # ── Step 3: Normalise results ────────────────────────────────────────────
    from evalplatform.core.schemas import JudgeResult

    final_judge_results = []
    for jr in judge_results_raw:
        if isinstance(jr, Exception):
            # Convert unexpected exceptions into a structured error JudgeResult
            # so downstream code always deals with the same type.
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

    # "partial" = the LLM succeeded but at least one judge errored out
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
        tokens_used=resp_tokens,
        latency_ms=resp_latency_ms,
    )


def _compute_aggregates(samples: list[SampleResult]) -> dict[int, AggregateScore]:
    """Compute per-judge aggregate scores across all samples.

    Iterates every sample's judge results and collects the numeric scores,
    grouped by `judge_index`. Only scores with status "ok" and a non-None
    value are counted — error results are excluded from statistics.

    Returns a dict keyed by judge_index where each value is an AggregateScore
    containing mean, min, max, and count.  Judges that produced zero valid
    scores are omitted from the output entirely.

    Args:
        samples: All SampleResult objects from a completed eval run.

    Returns:
        Dict mapping judge_index → AggregateScore with summary statistics.
    """
    # Group raw numeric scores by judge_index
    scores_by_judge: dict[int, list[int]] = {}
    for sample in samples:
        for jr in sample.judge_results:
            if jr.status == JudgeResultStatus.ok and jr.score is not None:
                scores_by_judge.setdefault(jr.judge_index, []).append(jr.score)

    # Compute summary statistics for each judge that had at least one valid score
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
    tracer: Tracer | None = None,
) -> EvalRunResult:
    """Execute an eval run end-to-end.

    This is the top-level entry point called by both the CLI script and the
    FastAPI background task. It orchestrates the full pipeline:

      1. Parse the model string and build all judge instances.
      2. Load the JSONL dataset into memory.
      3. Create a semaphore to cap concurrent LLM calls.
      4. Kick off all samples as concurrent async tasks using asyncio.as_completed,
         so results trickle in as they finish (not waiting for all to complete).
      5. After each sample, fire the optional status_callback so callers can
         update a progress bar or database record.
      6. Sort the final sample list by row_index for deterministic output order.
      7. Compute per-judge aggregate scores.
      8. Return the full EvalRunResult.

    Concurrency model:
        All samples run as concurrent async tasks. The asyncio.Semaphore inside
        _evaluate_sample caps the number of *simultaneous LLM API calls* to
        config.max_concurrency. Judges within each sample also run in parallel
        (asyncio.gather inside _evaluate_sample).

    Args:
        config:          Validated EvalConfig from the YAML config file.
        status_callback: Optional async function ``(completed: int, total: int) -> None``
                         called after each sample finishes. Used by the background
                         task to update the DB progress counter.
        tracer:          Optional Tracer instance. When provided, wraps the entire
                         run and each sample/llm_call/judge_execution in named spans.

    Returns:
        EvalRunResult with per-sample scores, aggregate stats, and row counts.
    """
    # Split "provider/model" → individual parts (e.g. "gemini/gemini-2.5-flash")
    provider_name, model_name = config.model.split("/", 1)
    judges = _build_judges(config)
    rows = _load_dataset(config.dataset)
    # Single shared semaphore ensures we never exceed max_concurrency LLM calls at once
    semaphore = asyncio.Semaphore(config.max_concurrency)

    # Wrap the entire run in a root span when tracing is enabled
    root_ctx = (
        tracer.span("eval_run", provider=provider_name, model=model_name)
        if tracer is not None
        else nullcontext()
    )

    sample_results: list[SampleResult] = []

    async with root_ctx:

        async def _run_one(idx: int, row: dict[str, str]) -> SampleResult:
            """Thin wrapper to pass shared context into _evaluate_sample."""
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

        # Create one coroutine per dataset row, then consume them as they complete.
        # asyncio.as_completed yields futures in completion order (not submission order),
        # so faster samples are processed first and the callback fires ASAP.
        tasks = [_run_one(idx, row) for idx, row in enumerate(rows)]
        for completed, coro in enumerate(asyncio.as_completed(tasks), 1):
            result = await coro
            sample_results.append(result)
            # Notify the caller (e.g., background task DB updater) of progress
            if status_callback is not None:
                await status_callback(completed, len(rows))

    # Re-sort by original row_index because as_completed yields in arbitrary order
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
