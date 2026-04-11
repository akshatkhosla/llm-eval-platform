"""Tests for the tracing layer: Tracer, TraceSpan/EvalTrace models, and the API endpoint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from evalplatform.api.app import app
from evalplatform.db.models import EvalRun, RunStatus
from evalplatform.db.session import get_session
from evalplatform.tracing.instrumentor import Tracer
from evalplatform.tracing.trace_models import EvalTrace

# ── Constants ──────────────────────────────────────────────────────────

BASE_URL = "http://test"
EVALS_URL = "/api/v1/evals"


# ── Fixtures ───────────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


async def _override_get_session():  # type: ignore[return]
    yield _mock_session()


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():  # type: ignore[return]
    yield
    app.dependency_overrides.clear()


def _set_session_override() -> None:
    app.dependency_overrides[get_session] = _override_get_session


def _async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url=BASE_URL,
    )


def _make_run(**kwargs: object) -> EvalRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "test-run",
        "config_yaml": "",
        "status": RunStatus.completed,
        "provider": "gemini",
        "model": "gemini-1.5-flash",
        "created_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        "started_at": None,
        "completed_at": None,
        "error_message": None,
        "total_samples": None,
        "completed_samples": 0,
        "aggregate_scores": None,
        "total_tokens": 0,
        "total_latency_ms": 0.0,
        "trace_data": None,
    }
    defaults.update(kwargs)
    return EvalRun(**defaults)  # type: ignore[arg-type]


# ── Tracer unit tests ──────────────────────────────────────────────────


async def test_single_span_builds_trace() -> None:
    """A tracer with one root span produces a valid EvalTrace."""
    run_id = uuid.uuid4()
    tracer = Tracer(run_id)

    async with tracer.span("eval_run", provider="gemini", model="flash"):
        pass

    trace = tracer.build_trace()

    assert trace.run_id == run_id
    assert trace.total_spans == 1
    assert trace.root_span.name == "eval_run"
    assert trace.root_span.parent_id is None
    assert trace.root_span.attributes["provider"] == "gemini"
    assert trace.root_span.attributes["model"] == "flash"
    assert trace.root_span.status == "ok"
    assert trace.root_span.duration_ms is not None
    assert trace.root_span.duration_ms >= 0.0
    assert trace.total_duration_ms == trace.root_span.duration_ms


async def test_nested_spans_build_correct_tree() -> None:
    """Child spans are nested under their parent in the trace tree."""
    run_id = uuid.uuid4()
    tracer = Tracer(run_id)

    async with tracer.span("eval_run"), tracer.span("sample_execution", sample_index=0):
        async with tracer.span("llm_call", provider="gemini"):
            pass
        async with tracer.span("judge_execution", judge_index=0):
            pass

    trace = tracer.build_trace()

    assert trace.total_spans == 4
    root = trace.root_span
    assert root.name == "eval_run"
    assert len(root.children) == 1

    sample = root.children[0]
    assert sample.name == "sample_execution"
    assert sample.attributes["sample_index"] == 0
    assert sample.parent_id == root.span_id
    assert len(sample.children) == 2

    llm, judge = sample.children[0], sample.children[1]
    assert llm.name == "llm_call"
    assert llm.parent_id == sample.span_id
    assert judge.name == "judge_execution"
    assert judge.parent_id == sample.span_id


async def test_multiple_samples_under_root() -> None:
    """Multiple sample_execution spans all appear as children of eval_run."""
    run_id = uuid.uuid4()
    tracer = Tracer(run_id)

    async with tracer.span("eval_run"):
        for i in range(3):
            async with tracer.span("sample_execution", sample_index=i):
                pass

    trace = tracer.build_trace()

    assert trace.total_spans == 4  # root + 3 samples
    assert len(trace.root_span.children) == 3
    sample_names = [c.name for c in trace.root_span.children]
    assert all(n == "sample_execution" for n in sample_names)


async def test_span_records_error_status_on_exception() -> None:
    """A span that raises an exception gets status='error'."""
    run_id = uuid.uuid4()
    tracer = Tracer(run_id)

    with pytest.raises(ValueError):
        async with tracer.span("eval_run"):
            async with tracer.span("sample_execution"):
                raise ValueError("boom")

    trace = tracer.build_trace()
    root = trace.root_span
    sample = root.children[0]

    assert sample.status == "error"
    assert "boom" in str(sample.attributes.get("error", ""))


async def test_span_has_timing_information() -> None:
    """Each span records start_time, end_time, and duration_ms."""
    tracer = Tracer(uuid.uuid4())
    async with tracer.span("eval_run"):
        pass

    span = tracer.build_trace().root_span
    assert span.start_time is not None
    assert span.end_time is not None
    assert isinstance(span.duration_ms, float)
    assert span.end_time >= span.start_time


async def test_build_trace_raises_with_no_spans() -> None:
    """build_trace() raises RuntimeError when no spans have been recorded."""
    tracer = Tracer(uuid.uuid4())
    with pytest.raises(RuntimeError, match="No spans recorded"):
        tracer.build_trace()


async def test_concurrent_samples_nest_correctly() -> None:
    """Concurrent sample_execution tasks each get their own child spans."""
    import asyncio

    run_id = uuid.uuid4()
    tracer = Tracer(run_id)

    async def run_sample(idx: int) -> None:
        async with tracer.span("sample_execution", sample_index=idx):
            async with tracer.span("llm_call"):
                await asyncio.sleep(0)  # yield to event loop
            async with tracer.span("judge_execution"):
                await asyncio.sleep(0)

    async with tracer.span("eval_run"):
        await asyncio.gather(run_sample(0), run_sample(1), run_sample(2))

    trace = tracer.build_trace()

    # 1 root + 3 samples * 3 spans each = 10 total
    assert trace.total_spans == 10
    root = trace.root_span
    assert len(root.children) == 3

    for sample_span in root.children:
        assert sample_span.name == "sample_execution"
        # Each sample has exactly llm_call + judge_execution as children
        child_names = {c.name for c in sample_span.children}
        assert child_names == {"llm_call", "judge_execution"}


async def test_eval_trace_serialises_to_json() -> None:
    """EvalTrace can be round-tripped through model_dump/model_validate."""
    tracer = Tracer(uuid.uuid4())
    async with tracer.span("eval_run", provider="ollama"), tracer.span("sample_execution"):
        pass

    trace = tracer.build_trace()
    raw = trace.model_dump(mode="json")
    restored = EvalTrace.model_validate(raw)

    assert restored.run_id == trace.run_id
    assert restored.total_spans == trace.total_spans
    assert restored.root_span.name == "eval_run"
    assert len(restored.root_span.children) == 1
    assert restored.root_span.children[0].name == "sample_execution"


async def test_trace_span_attributes_recorded() -> None:
    """All expected attributes are present on llm_call and judge_execution spans."""
    tracer = Tracer(uuid.uuid4())

    async with tracer.span("eval_run"), tracer.span("sample_execution", sample_index=0):
        async with tracer.span(
            "llm_call",
            provider="gemini",
            model="flash",
            input_tokens=10,
            output_tokens=50,
            latency_ms=123.4,
            status="ok",
        ):
            pass
        async with tracer.span(
            "judge_execution",
            judge_index=0,
            judge_type="ContainsKeywordJudge",
            judge_score=10,
            status="ok",
        ):
            pass

    root = tracer.build_trace().root_span
    sample = root.children[0]
    llm = sample.children[0]
    judge = sample.children[1]

    assert llm.attributes["provider"] == "gemini"
    assert llm.attributes["input_tokens"] == 10
    assert llm.attributes["output_tokens"] == 50
    assert llm.attributes["latency_ms"] == 123.4

    assert judge.attributes["judge_index"] == 0
    assert judge.attributes["judge_score"] == 10


# ── API endpoint tests ─────────────────────────────────────────────────


async def test_get_traces_returns_eval_trace() -> None:
    """GET /{run_id}/traces returns 200 with the stored EvalTrace payload."""
    run_id = uuid.uuid4()

    # Build a minimal trace and serialise it as the stored payload
    tracer = Tracer(run_id)
    async with tracer.span("eval_run", provider="gemini"), tracer.span("sample_execution"):
        pass
    raw_trace = tracer.build_trace().model_dump(mode="json")

    run = _make_run(id=run_id, trace_data=raw_trace)
    _set_session_override()

    with (
        patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=run)),
        patch("evalplatform.db.repos.get_trace", new=AsyncMock(return_value=raw_trace)),
    ):
        async with _async_client() as client:
            response = await client.get(f"{EVALS_URL}/{run_id}/traces")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["total_spans"] == 2
    assert body["root_span"]["name"] == "eval_run"
    assert len(body["root_span"]["children"]) == 1
    assert body["root_span"]["children"][0]["name"] == "sample_execution"


async def test_get_traces_run_not_found() -> None:
    """GET /{run_id}/traces returns 404 when the run does not exist."""
    unknown = uuid.uuid4()
    _set_session_override()

    with patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=None)):
        async with _async_client() as client:
            response = await client.get(f"{EVALS_URL}/{unknown}/traces")

    assert response.status_code == 404
    assert str(unknown) in response.json()["detail"]


async def test_get_traces_not_yet_stored() -> None:
    """GET /{run_id}/traces returns 404 when the trace has not been stored yet."""
    run_id = uuid.uuid4()
    run = _make_run(id=run_id, trace_data=None)
    _set_session_override()

    with (
        patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=run)),
        patch("evalplatform.db.repos.get_trace", new=AsyncMock(return_value=None)),
    ):
        async with _async_client() as client:
            response = await client.get(f"{EVALS_URL}/{run_id}/traces")

    assert response.status_code == 404
    assert "still be in progress" in response.json()["detail"]
