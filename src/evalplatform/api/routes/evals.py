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
