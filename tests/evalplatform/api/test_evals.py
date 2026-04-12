"""Integration tests for the /api/v1/evals endpoints using httpx.AsyncClient."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from evalplatform.api.app import app
from evalplatform.db.models import EvalResult, EvalRun, ResultStatus, RunStatus
from evalplatform.db.session import get_session

# ── Constants ──────────────────────────────────────────────────────────

VALID_YAML = """\
eval:
  model: gemini/gemini-1.5-flash
  dataset: data/prompts.jsonl
  judges:
    - type: contains_keyword
      keyword: python
"""

INVALID_YAML = """\
no_eval_key:
  model: gemini/gemini-1.5-flash
"""

BASE_URL = "http://test"
EVALS_URL = "/api/v1/evals"


# ── Fixtures ───────────────────────────────────────────────────────────


def _make_run(**kwargs: object) -> EvalRun:
    """Build a minimal EvalRun stub with sensible defaults."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "gemini-gemini-1.5-flash",
        "config_yaml": VALID_YAML,
        "status": RunStatus.pending,
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
    }
    defaults.update(kwargs)
    return EvalRun(**defaults)  # type: ignore[arg-type]


def _make_result(run_id: uuid.UUID, **kwargs: object) -> EvalResult:
    """Build a minimal EvalResult stub with sensible defaults."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "run_id": run_id,
        "sample_index": 0,
        "input_text": "Write a python script",
        "model_output": "Here is a python script",
        "expected_output": None,
        "judge_scores": {"contains_keyword": {"score": 1.0}},
        "tokens_used": 50,
        "latency_ms": 200.0,
        "status": ResultStatus.success,
        "error_message": None,
    }
    defaults.update(kwargs)
    return EvalResult(**defaults)  # type: ignore[arg-type]


def _mock_session() -> AsyncMock:
    """Return an AsyncMock that behaves like an AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


async def _override_get_session() -> AsyncGenerator[AsyncMock, None]:
    """Dependency override: yield a mock session instead of a real DB session."""
    yield _mock_session()


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> AsyncGenerator[None, None]:
    """Ensure dependency overrides are cleared after every test."""
    yield  # type: ignore[misc]
    app.dependency_overrides.clear()


def _set_session_override() -> None:
    app.dependency_overrides[get_session] = _override_get_session


# ── Helper ─────────────────────────────────────────────────────────────


def _async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url=BASE_URL,
    )


# ── Tests ──────────────────────────────────────────────────────────────


async def test_health() -> None:
    """GET /health returns 200 with status ok and version 0.1.0."""
    async with _async_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


async def test_create_eval_json() -> None:
    """POST /api/v1/evals with JSON body returns 202 with run_id and status pending."""
    run = _make_run()
    _set_session_override()

    with (
        patch("evalplatform.db.repos.create_run", new=AsyncMock(return_value=run)) as mock_create,
        patch("evalplatform.api.routes.evals.run_eval_background", new=AsyncMock()),
    ):
        async with _async_client() as client:
            response = await client.post(
                EVALS_URL,
                json={"config_yaml": VALID_YAML, "name": "my-eval"},
            )

    assert response.status_code == 202
    body = response.json()
    assert body["run_id"] == str(run.id)
    assert body["status"] == "pending"
    mock_create.assert_awaited_once()
    _, kwargs = mock_create.call_args
    assert kwargs["name"] == "my-eval"
    assert kwargs["provider"] == "gemini"
    assert kwargs["model"] == "gemini-1.5-flash"


async def test_create_eval_yaml_content_type() -> None:
    """POST with Content-Type: text/yaml body returns 202."""
    run = _make_run()
    _set_session_override()

    with (
        patch("evalplatform.db.repos.create_run", new=AsyncMock(return_value=run)),
        patch("evalplatform.api.routes.evals.run_eval_background", new=AsyncMock()),
    ):
        async with _async_client() as client:
            response = await client.post(
                EVALS_URL,
                content=VALID_YAML.encode(),
                headers={"Content-Type": "text/yaml"},
            )

    assert response.status_code == 202
    body = response.json()
    assert body["run_id"] == str(run.id)
    assert body["status"] == "pending"


async def test_create_eval_missing_config_yaml() -> None:
    """POST JSON without config_yaml returns 422."""
    _set_session_override()

    with patch("evalplatform.api.routes.evals.run_eval_background", new=AsyncMock()):
        async with _async_client() as client:
            response = await client.post(EVALS_URL, json={"name": "no-config"})

    assert response.status_code == 422


async def test_create_eval_invalid_yaml() -> None:
    """POST with YAML missing the eval key returns 400."""
    _set_session_override()

    with patch("evalplatform.api.routes.evals.run_eval_background", new=AsyncMock()):
        async with _async_client() as client:
            response = await client.post(EVALS_URL, json={"config_yaml": INVALID_YAML})

    assert response.status_code == 400
    assert "Invalid config" in response.json()["detail"]


async def test_list_evals_empty() -> None:
    """GET /api/v1/evals returns 200 with an empty list when there are no runs."""
    _set_session_override()

    with patch("evalplatform.db.repos.list_runs", new=AsyncMock(return_value=[])):
        async with _async_client() as client:
            response = await client.get(EVALS_URL)

    assert response.status_code == 200
    assert response.json() == []


async def test_list_evals_with_status_filter() -> None:
    """GET /api/v1/evals?status=completed passes status to list_runs."""
    run = _make_run(status=RunStatus.completed)
    _set_session_override()

    with patch("evalplatform.db.repos.list_runs", new=AsyncMock(return_value=[run])) as mock_list:
        async with _async_client() as client:
            response = await client.get(EVALS_URL, params={"status": "completed"})

    assert response.status_code == 200
    mock_list.assert_awaited_once()
    _, kwargs = mock_list.call_args
    assert kwargs["status"] == "completed"


async def test_get_eval_found() -> None:
    """GET /api/v1/evals/{run_id} returns 200 with run detail fields."""
    run = _make_run()
    run_id = cast(uuid.UUID, run.id)
    _set_session_override()

    with patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=run)):
        async with _async_client() as client:
            response = await client.get(f"{EVALS_URL}/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["name"] == run.name
    assert body["status"] == run.status
    assert body["provider"] == run.provider
    assert body["model"] == run.model
    assert body["completed_samples"] == 0
    assert body["total_tokens"] == 0
    assert body["total_latency_ms"] == 0.0
    assert body["error_message"] is None
    assert body["aggregate_scores"] is None


async def test_get_eval_not_found() -> None:
    """GET /api/v1/evals/{run_id} returns 404 for an unknown run_id."""
    unknown_id = uuid.uuid4()
    _set_session_override()

    with patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=None)):
        async with _async_client() as client:
            response = await client.get(f"{EVALS_URL}/{unknown_id}")

    assert response.status_code == 404
    assert str(unknown_id) in response.json()["detail"]


async def test_get_eval_results_default_sort() -> None:
    """GET /{run_id}/results returns results sorted by sample_index ascending by default."""
    run = _make_run()
    run_id = cast(uuid.UUID, run.id)
    results = [
        _make_result(run_id, sample_index=2),
        _make_result(run_id, sample_index=0),
        _make_result(run_id, sample_index=1),
    ]
    _set_session_override()

    with (
        patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=run)),
        patch("evalplatform.db.repos.get_results_for_run", new=AsyncMock(return_value=results)),
    ):
        async with _async_client() as client:
            response = await client.get(f"{EVALS_URL}/{run_id}/results")

    assert response.status_code == 200
    body = response.json()
    returned_indices = [item["sample_index"] for item in body["results"]]
    assert returned_indices == [0, 1, 2]


async def test_get_eval_results_sort_by_score() -> None:
    """GET /{run_id}/results?sort_by=score&order=desc returns highest scorer first."""
    run = _make_run()
    run_id = cast(uuid.UUID, run.id)
    results = [
        _make_result(
            run_id,
            sample_index=0,
            judge_scores={"k": {"score": 0.2}},
        ),
        _make_result(
            run_id,
            sample_index=1,
            judge_scores={"k": {"score": 0.9}},
        ),
        _make_result(
            run_id,
            sample_index=2,
            judge_scores={"k": {"score": 0.5}},
        ),
    ]
    _set_session_override()

    with (
        patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=run)),
        patch("evalplatform.db.repos.get_results_for_run", new=AsyncMock(return_value=results)),
    ):
        async with _async_client() as client:
            response = await client.get(
                f"{EVALS_URL}/{run_id}/results",
                params={"sort_by": "score", "order": "desc"},
            )

    assert response.status_code == 200
    body = response.json()
    returned_indices = [item["sample_index"] for item in body["results"]]
    # sample_index 1 (score 0.9) > 2 (0.5) > 0 (0.2)
    assert returned_indices == [1, 2, 0]


async def test_get_eval_results_run_not_found() -> None:
    """GET /{run_id}/results returns 404 when run doesn't exist."""
    unknown_id = uuid.uuid4()
    _set_session_override()

    with patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=None)):
        async with _async_client() as client:
            response = await client.get(f"{EVALS_URL}/{unknown_id}/results")

    assert response.status_code == 404
    assert str(unknown_id) in response.json()["detail"]


async def test_rerun_eval() -> None:
    """POST /{run_id}/rerun creates a new run with the same config and returns new run_id."""
    parent_run = _make_run()
    parent_id = cast(uuid.UUID, parent_run.id)
    new_run = _make_run(id=uuid.uuid4(), name=parent_run.name)
    _set_session_override()

    with (
        patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=parent_run)),
        patch(
            "evalplatform.db.repos.create_run", new=AsyncMock(return_value=new_run)
        ) as mock_create,
        patch("evalplatform.api.routes.evals.run_eval_background", new=AsyncMock()),
    ):
        async with _async_client() as client:
            response = await client.post(f"{EVALS_URL}/{parent_id}/rerun")

    assert response.status_code == 202
    body = response.json()
    assert body["run_id"] == str(new_run.id)
    assert body["status"] == "pending"
    assert body["parent_run_id"] == str(parent_id)

    mock_create.assert_awaited_once()
    _, kwargs = mock_create.call_args
    assert kwargs["name"] == parent_run.name
    assert kwargs["config_yaml"] == parent_run.config_yaml
    assert kwargs["provider"] == parent_run.provider
    assert kwargs["model"] == parent_run.model


async def test_rerun_eval_not_found() -> None:
    """POST /{run_id}/rerun returns 404 when the parent run doesn't exist."""
    unknown_id = uuid.uuid4()
    _set_session_override()

    with patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=None)):
        async with _async_client() as client:
            response = await client.post(f"{EVALS_URL}/{unknown_id}/rerun")

    assert response.status_code == 404
    assert str(unknown_id) in response.json()["detail"]


# ── Comparison tests ───────────────────────────────────────────────────


async def test_compare_evals_success() -> None:
    """GET /compare returns 200 with per-evaluator scores and flagged samples."""
    run_a_id = uuid.uuid4()
    run_b_id = uuid.uuid4()
    run_a = _make_run(id=run_a_id, model="gemini-1.5-flash")
    run_b = _make_run(id=run_b_id, model="gemini-1.5-pro")

    # Create results for both runs with different scores
    results_a = [
        _make_result(
            run_a_id,
            sample_index=0,
            judge_scores={"contains_keyword": {"score": 8.0}},
        ),
        _make_result(
            run_a_id,
            sample_index=1,
            judge_scores={"contains_keyword": {"score": 6.0}},
        ),
    ]
    results_b = [
        _make_result(
            run_b_id,
            sample_index=0,
            judge_scores={"contains_keyword": {"score": 9.0}},
        ),
        _make_result(
            run_b_id,
            sample_index=1,
            judge_scores={"contains_keyword": {"score": 5.0}},
        ),
    ]
    _set_session_override()

    with (
        patch("evalplatform.db.repos.get_run") as mock_get_run,
        patch(
            "evalplatform.db.repos.get_results_for_runs",
            new=AsyncMock(return_value={run_a_id: results_a, run_b_id: results_b}),
        ),
    ):
        mock_get_run.side_effect = [run_a, run_b]
        async with _async_client() as client:
            response = await client.get(
                f"{EVALS_URL}/compare",
                params={"run_ids": f"{run_a_id},{run_b_id}", "flagged_limit": "1"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id_a"] == str(run_a_id)
    assert body["run_id_b"] == str(run_b_id)

    # Verify judge summaries
    assert len(body["judge_summaries"]) == 1
    judge_summary = body["judge_summaries"][0]
    assert judge_summary["judge_key"] == "contains_keyword"
    assert judge_summary["mean_a"] == 7.0  # (8 + 6) / 2
    assert judge_summary["mean_b"] == 7.0  # (9 + 5) / 2
    assert judge_summary["delta"] == 0.0

    # Verify samples
    assert len(body["samples"]) == 2
    sample_0 = body["samples"][0]
    assert sample_0["sample_index"] == 0
    assert sample_0["judges"]["contains_keyword"]["score_a"] == 8.0
    assert sample_0["judges"]["contains_keyword"]["score_b"] == 9.0
    assert sample_0["judges"]["contains_keyword"]["delta"] == 1.0
    assert sample_0["avg_delta"] == 1.0

    # Verify flagged samples - with flagged_limit=1, only top 1 sample by abs(delta) is flagged
    assert len(body["flagged_samples"]) == 1
    assert body["flagged_samples"][0]["sample_index"] in [0, 1]  # Either could be first due to tie


async def test_compare_evals_run_not_found() -> None:
    """GET /compare returns 404 when one run doesn't exist."""
    run_a_id = uuid.uuid4()
    unknown_id = uuid.uuid4()
    run_a = _make_run(id=run_a_id)
    _set_session_override()

    with patch("evalplatform.db.repos.get_run") as mock_get_run:
        mock_get_run.side_effect = [run_a, None]
        async with _async_client() as client:
            response = await client.get(
                f"{EVALS_URL}/compare",
                params={"run_ids": f"{run_a_id},{unknown_id}"},
            )

    assert response.status_code == 404
    assert str(unknown_id) in response.json()["detail"]


async def test_compare_evals_invalid_run_ids_format() -> None:
    """GET /compare returns 422 for invalid run_ids format."""
    _set_session_override()

    with patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=None)):
        async with _async_client() as client:
            # Only one UUID provided
            response = await client.get(
                f"{EVALS_URL}/compare",
                params={"run_ids": str(uuid.uuid4())},
            )

    assert response.status_code == 422
    assert "two comma-separated" in response.json()["detail"]


async def test_compare_evals_invalid_uuid() -> None:
    """GET /compare returns 422 for invalid UUID format."""
    _set_session_override()

    with patch("evalplatform.db.repos.get_run", new=AsyncMock(return_value=None)):
        async with _async_client() as client:
            response = await client.get(
                f"{EVALS_URL}/compare",
                params={"run_ids": f"{uuid.uuid4()},not-a-uuid"},
            )

    assert response.status_code == 422
    assert "invalid UUID" in response.json()["detail"]


async def test_compare_evals_mismatched_samples() -> None:
    """GET /compare handles runs with different sample sets."""
    run_a_id = uuid.uuid4()
    run_b_id = uuid.uuid4()
    run_a = _make_run(id=run_a_id)
    run_b = _make_run(id=run_b_id)

    # Run A has samples 0, 1; Run B has samples 1, 2
    results_a = [
        _make_result(run_a_id, sample_index=0, judge_scores={"j1": {"score": 8.0}}),
        _make_result(run_a_id, sample_index=1, judge_scores={"j1": {"score": 6.0}}),
    ]
    results_b = [
        _make_result(run_b_id, sample_index=1, judge_scores={"j1": {"score": 7.0}}),
        _make_result(run_b_id, sample_index=2, judge_scores={"j1": {"score": 9.0}}),
    ]
    _set_session_override()

    with (
        patch("evalplatform.db.repos.get_run") as mock_get_run,
        patch(
            "evalplatform.db.repos.get_results_for_runs",
            new=AsyncMock(return_value={run_a_id: results_a, run_b_id: results_b}),
        ),
    ):
        mock_get_run.side_effect = [run_a, run_b]
        async with _async_client() as client:
            response = await client.get(
                f"{EVALS_URL}/compare",
                params={"run_ids": f"{run_a_id},{run_b_id}"},
            )

    assert response.status_code == 200
    body = response.json()

    # Should have all three samples (0, 1, 2)
    assert len(body["samples"]) == 3
    sample_indices = [s["sample_index"] for s in body["samples"]]
    assert sample_indices == [0, 1, 2]

    # Sample 0: only in run_a, so score_b should be None
    sample_0 = body["samples"][0]
    assert sample_0["judges"]["j1"]["score_a"] == 8.0
    assert sample_0["judges"]["j1"]["score_b"] is None
    assert sample_0["judges"]["j1"]["delta"] is None
    assert sample_0["avg_score_a"] == 8.0
    assert sample_0["avg_score_b"] is None
    assert sample_0["avg_delta"] is None

    # Sample 1: in both, delta should be 7.0 - 6.0 = 1.0
    sample_1 = body["samples"][1]
    assert sample_1["judges"]["j1"]["score_a"] == 6.0
    assert sample_1["judges"]["j1"]["score_b"] == 7.0
    assert sample_1["judges"]["j1"]["delta"] == 1.0
    assert sample_1["avg_delta"] == 1.0

    # Sample 2: only in run_b, so score_a should be None
    sample_2 = body["samples"][2]
    assert sample_2["judges"]["j1"]["score_a"] is None
    assert sample_2["judges"]["j1"]["score_b"] == 9.0
    assert sample_2["judges"]["j1"]["delta"] is None
    assert sample_2["avg_score_a"] is None
    assert sample_2["avg_score_b"] == 9.0
    assert sample_2["avg_delta"] is None
