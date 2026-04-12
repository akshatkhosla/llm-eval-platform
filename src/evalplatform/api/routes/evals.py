"""FastAPI routes for eval run management."""

from __future__ import annotations

import uuid
from datetime import datetime

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from evalplatform.api.background import run_eval_background
from evalplatform.core.config_loader import load_config_from_string
from evalplatform.db import repos
from evalplatform.db.session import AsyncSessionLocal, get_session
from evalplatform.tracing.trace_models import EvalTrace  # noqa: TCH001

# ── Response models ────────────────────────────────────────────────────


class CreateRunResponse(BaseModel):
    run_id: uuid.UUID
    status: str


class EvalRunSummary(BaseModel):
    run_id: uuid.UUID
    name: str
    status: str
    provider: str
    model: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    total_samples: int | None
    completed_samples: int
    total_tokens: int
    total_latency_ms: float


class EvalRunDetail(EvalRunSummary):
    error_message: str | None
    aggregate_scores: dict[str, object] | None


class EvalResultItem(BaseModel):
    id: uuid.UUID
    sample_index: int
    input_text: str
    model_output: str | None
    expected_output: str | None
    judge_scores: dict[str, object]
    tokens_used: int
    latency_ms: float
    status: str
    error_message: str | None


class EvalResultsResponse(BaseModel):
    run_id: uuid.UUID
    results: list[EvalResultItem]


class RerunResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    parent_run_id: uuid.UUID


class JudgeScorePair(BaseModel):
    score_a: float | None  # score from run A
    score_b: float | None  # score from run B
    delta: float | None  # score_b - score_a


class SampleComparison(BaseModel):
    sample_index: int
    input_text: str
    judges: dict[str, JudgeScorePair]  # keyed by judge name
    avg_score_a: float | None
    avg_score_b: float | None
    avg_delta: float | None  # avg_score_b - avg_score_a
    flagged: bool  # True = large score change


class JudgeSummary(BaseModel):
    judge_key: str
    mean_a: float | None
    mean_b: float | None
    delta: float | None  # mean_b - mean_a


class CompareResponse(BaseModel):
    run_id_a: uuid.UUID
    run_id_b: uuid.UUID
    run_a: EvalRunSummary
    run_b: EvalRunSummary
    judge_summaries: list[JudgeSummary]
    samples: list[SampleComparison]
    flagged_samples: list[SampleComparison]


# ── Helpers ────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/evals", tags=["evals"])


def _to_summary(run: object) -> EvalRunSummary:
    return EvalRunSummary(
        run_id=run.id,  # type: ignore[attr-defined]
        name=run.name,  # type: ignore[attr-defined]
        status=run.status,  # type: ignore[attr-defined]
        provider=run.provider,  # type: ignore[attr-defined]
        model=run.model,  # type: ignore[attr-defined]
        created_at=run.created_at,  # type: ignore[attr-defined]
        started_at=run.started_at,  # type: ignore[attr-defined]
        completed_at=run.completed_at,  # type: ignore[attr-defined]
        total_samples=run.total_samples,  # type: ignore[attr-defined]
        completed_samples=run.completed_samples,  # type: ignore[attr-defined]
        total_tokens=run.total_tokens,  # type: ignore[attr-defined]
        total_latency_ms=run.total_latency_ms,  # type: ignore[attr-defined]
    )


def _to_detail(run: object) -> EvalRunDetail:
    return EvalRunDetail(
        run_id=run.id,  # type: ignore[attr-defined]
        name=run.name,  # type: ignore[attr-defined]
        status=run.status,  # type: ignore[attr-defined]
        provider=run.provider,  # type: ignore[attr-defined]
        model=run.model,  # type: ignore[attr-defined]
        created_at=run.created_at,  # type: ignore[attr-defined]
        started_at=run.started_at,  # type: ignore[attr-defined]
        completed_at=run.completed_at,  # type: ignore[attr-defined]
        total_samples=run.total_samples,  # type: ignore[attr-defined]
        completed_samples=run.completed_samples,  # type: ignore[attr-defined]
        total_tokens=run.total_tokens,  # type: ignore[attr-defined]
        total_latency_ms=run.total_latency_ms,  # type: ignore[attr-defined]
        error_message=run.error_message,  # type: ignore[attr-defined]
        aggregate_scores=run.aggregate_scores,  # type: ignore[attr-defined]
    )


def _avg_score(result: object) -> float:
    """Compute mean judge score across all judges for sorting purposes."""
    scores = [
        v["score"]
        for v in result.judge_scores.values()  # type: ignore[attr-defined]
        if isinstance(v, dict) and v.get("score") is not None
    ]
    return sum(scores) / len(scores) if scores else 0.0


# ── Routes ─────────────────────────────────────────────────────────────


@router.post("", response_model=CreateRunResponse, status_code=202)
async def create_eval(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> CreateRunResponse:
    """Start a new eval run from a YAML config.

    Accepts ``Content-Type: text/yaml`` (raw YAML body) or JSON with a
    ``config_yaml`` field (and optional ``name`` field).
    """
    content_type = request.headers.get("content-type", "")
    run_name: str | None = None

    if "yaml" in content_type:
        body_bytes = await request.body()
        yaml_str = body_bytes.decode("utf-8")
    else:
        body_json = await request.json()
        yaml_str = body_json.get("config_yaml")
        if not yaml_str:
            raise HTTPException(status_code=422, detail="config_yaml is required")
        run_name = body_json.get("name")

    try:
        config = load_config_from_string(yaml_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid config: {exc}") from exc

    if not run_name:
        try:
            raw = yaml.safe_load(yaml_str)
            run_name = raw.get("name") if isinstance(raw, dict) else None
        except Exception:
            run_name = None
        if not run_name:
            provider_name, model_name = config.model.split("/", 1)
            run_name = f"{provider_name}-{model_name}"

    provider_name, model_name = config.model.split("/", 1)

    run = await repos.create_run(
        session,
        name=run_name,
        config_yaml=yaml_str,
        provider=provider_name,
        model=model_name,
    )

    background_tasks.add_task(run_eval_background, run.id, config, AsyncSessionLocal)

    return CreateRunResponse(run_id=run.id, status=run.status)


@router.get("", response_model=list[EvalRunSummary])
async def list_evals(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[EvalRunSummary]:
    """List eval runs with optional status filter and pagination."""
    runs = await repos.list_runs(session, status=status, limit=limit, offset=offset)
    return [_to_summary(r) for r in runs]


@router.get("/compare", response_model=CompareResponse)
async def compare_evals(
    run_ids: str = Query(..., description="Two run UUIDs, comma-separated"),
    flagged_limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> CompareResponse:
    """Compare two eval runs side by side.

    Returns per-evaluator scores, deltas, and flagged samples with big score changes.
    """
    # Parse two UUIDs from run_ids param
    parts = [p.strip() for p in run_ids.split(",")]
    if len(parts) != 2:
        raise HTTPException(
            status_code=422,
            detail="run_ids must be exactly two comma-separated UUIDs",
        )
    try:
        id_a, id_b = uuid.UUID(parts[0]), uuid.UUID(parts[1])
    except ValueError as err:
        raise HTTPException(status_code=422, detail="run_ids contains an invalid UUID") from err

    # Fetch both runs
    run_a = await repos.get_run(session, id_a)
    if run_a is None:
        raise HTTPException(status_code=404, detail=f"Run {id_a} not found")
    run_b = await repos.get_run(session, id_b)
    if run_b is None:
        raise HTTPException(status_code=404, detail=f"Run {id_b} not found")

    # Fetch results for both runs
    results_map = await repos.get_results_for_runs(session, [id_a, id_b])
    results_a = results_map.get(id_a, [])
    results_b = results_map.get(id_b, [])

    # Index results by sample_index
    by_index_a = {r.sample_index: r for r in results_a}  # type: ignore[attr-defined]
    by_index_b = {r.sample_index: r for r in results_b}  # type: ignore[attr-defined]

    # Get all unique sample indices
    all_indices = sorted(set(by_index_a.keys()) | set(by_index_b.keys()))

    # Build per-judge summaries (aggregate across samples)
    judge_scores_a: dict[str, list[float]] = {}
    judge_scores_b: dict[str, list[float]] = {}

    samples_list: list[SampleComparison] = []

    for idx in all_indices:
        result_a = by_index_a.get(idx)
        result_b = by_index_b.get(idx)

        # Build judges dict for this sample
        judges_dict: dict[str, JudgeScorePair] = {}

        # Extract judge scores from result_a
        if result_a:
            for judge_key, judge_data in result_a.judge_scores.items():  # type: ignore[attr-defined]
                score_a = None
                if isinstance(judge_data, dict):
                    raw_score = judge_data.get("score")
                    score_a = float(raw_score) if isinstance(raw_score, (int, float)) else None
                judges_dict.setdefault(
                    judge_key, JudgeScorePair(score_a=None, score_b=None, delta=None)
                )
                judges_dict[judge_key].score_a = score_a  # type: ignore[attr-defined]

        # Extract judge scores from result_b
        if result_b:
            for judge_key, judge_data in result_b.judge_scores.items():  # type: ignore[attr-defined]
                score_b = None
                if isinstance(judge_data, dict):
                    raw_score = judge_data.get("score")
                    score_b = float(raw_score) if isinstance(raw_score, (int, float)) else None
                judges_dict.setdefault(
                    judge_key, JudgeScorePair(score_a=None, score_b=None, delta=None)
                )
                judges_dict[judge_key].score_b = score_b  # type: ignore[attr-defined]

        # Compute deltas for each judge and aggregate per-judge stats
        for judge_key, pair in judges_dict.items():
            if pair.score_a is not None and pair.score_b is not None:
                pair.delta = pair.score_b - pair.score_a  # type: ignore[attr-defined]
            judge_scores_a.setdefault(judge_key, [])
            judge_scores_b.setdefault(judge_key, [])
            if pair.score_a is not None:
                judge_scores_a[judge_key].append(pair.score_a)
            if pair.score_b is not None:
                judge_scores_b[judge_key].append(pair.score_b)

        # Compute average scores for this sample
        scores_a = [p.score_a for p in judges_dict.values() if p.score_a is not None]
        scores_b = [p.score_b for p in judges_dict.values() if p.score_b is not None]
        avg_score_a = sum(scores_a) / len(scores_a) if scores_a else None
        avg_score_b = sum(scores_b) / len(scores_b) if scores_b else None
        avg_delta: float | None = None
        if avg_score_a is not None and avg_score_b is not None:
            avg_delta = avg_score_b - avg_score_a

        # Use input_text from whichever result has it
        input_text = ""
        if result_a:
            input_text = result_a.input_text  # type: ignore[attr-defined]
        elif result_b:
            input_text = result_b.input_text  # type: ignore[attr-defined]

        sample = SampleComparison(
            sample_index=idx,
            input_text=input_text,
            judges=judges_dict,
            avg_score_a=avg_score_a,
            avg_score_b=avg_score_b,
            avg_delta=avg_delta,
            flagged=False,  # Will update below
        )
        samples_list.append(sample)

    # Flag top samples by absolute delta
    samples_with_delta = [s for s in samples_list if s.avg_delta is not None]
    samples_with_delta.sort(key=lambda s: abs(s.avg_delta or 0), reverse=True)
    flagged_set = {s.sample_index for s in samples_with_delta[:flagged_limit]}

    # Update flagged status
    for sample in samples_list:
        if sample.sample_index in flagged_set:
            sample.flagged = True

    # Build flagged_samples list (top N)
    flagged_samples = [s for s in samples_list if s.flagged]

    # Build judge summaries
    judge_summary_list: list[JudgeSummary] = []
    all_judges = set(judge_scores_a.keys()) | set(judge_scores_b.keys())
    for judge_key in sorted(all_judges):
        scores_a = judge_scores_a.get(judge_key, [])
        scores_b = judge_scores_b.get(judge_key, [])
        mean_a = sum(scores_a) / len(scores_a) if scores_a else None
        mean_b = sum(scores_b) / len(scores_b) if scores_b else None
        delta: float | None = None
        if mean_a is not None and mean_b is not None:
            delta = mean_b - mean_a
        judge_summary_list.append(
            JudgeSummary(judge_key=judge_key, mean_a=mean_a, mean_b=mean_b, delta=delta)
        )

    return CompareResponse(
        run_id_a=id_a,
        run_id_b=id_b,
        run_a=_to_summary(run_a),
        run_b=_to_summary(run_b),
        judge_summaries=judge_summary_list,
        samples=samples_list,
        flagged_samples=flagged_samples,
    )


@router.get("/{run_id}/results", response_model=EvalResultsResponse)
async def get_eval_results(
    run_id: uuid.UUID,
    sort_by: str = Query(default="sample_index", pattern="^(sample_index|score)$"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    session: AsyncSession = Depends(get_session),
) -> EvalResultsResponse:
    """Get per-sample results for an eval run.

    Supports ``?sort_by=score`` or ``?sort_by=sample_index`` and
    ``?order=asc`` or ``?order=desc``.
    """
    run = await repos.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    results = await repos.get_results_for_run(session, run_id)
    reverse = order == "desc"

    if sort_by == "score":
        sorted_results = sorted(results, key=_avg_score, reverse=reverse)
    else:
        sorted_results = sorted(results, key=lambda r: r.sample_index, reverse=reverse)  # type: ignore[attr-defined]

    items = [
        EvalResultItem(
            id=r.id,  # type: ignore[attr-defined]
            sample_index=r.sample_index,  # type: ignore[attr-defined]
            input_text=r.input_text,  # type: ignore[attr-defined]
            model_output=r.model_output,  # type: ignore[attr-defined]
            expected_output=r.expected_output,  # type: ignore[attr-defined]
            judge_scores=r.judge_scores,  # type: ignore[attr-defined]
            tokens_used=r.tokens_used,  # type: ignore[attr-defined]
            latency_ms=r.latency_ms,  # type: ignore[attr-defined]
            status=r.status,  # type: ignore[attr-defined]
            error_message=r.error_message,  # type: ignore[attr-defined]
        )
        for r in sorted_results
    ]

    return EvalResultsResponse(run_id=run_id, results=items)


@router.get("/{run_id}", response_model=EvalRunDetail)
async def get_eval(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> EvalRunDetail:
    """Get the status and aggregate scores for an eval run."""
    run = await repos.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _to_detail(run)


@router.get("/{run_id}/traces", response_model=EvalTrace)
async def get_eval_traces(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> EvalTrace:
    """Return the full trace tree for a completed eval run.

    Returns 404 if the run does not exist or the trace has not been stored yet
    (e.g. the run is still in progress).
    """
    run = await repos.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    raw = await repos.get_trace(session, run_id)
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail=f"Trace for run {run_id} not found — the run may still be in progress",
        )
    return EvalTrace.model_validate(raw)


@router.post("/{run_id}/rerun", response_model=RerunResponse, status_code=202)
async def rerun_eval(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> RerunResponse:
    """Clone an existing run's config and start a new eval run."""
    parent = await repos.get_run(session, run_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    try:
        config = load_config_from_string(parent.config_yaml)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid stored config: {exc}") from exc

    new_run = await repos.create_run(
        session,
        name=parent.name,
        config_yaml=parent.config_yaml,
        provider=parent.provider,
        model=parent.model,
    )

    background_tasks.add_task(run_eval_background, new_run.id, config, AsyncSessionLocal)

    return RerunResponse(run_id=new_run.id, status=new_run.status, parent_run_id=run_id)
