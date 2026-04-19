"""Tests for the repository layer using mock async sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from evalplatform.db import repos
from evalplatform.db.models import EvalResult, EvalRun, ResultStatus, RunStatus


def _make_run(**kwargs: object) -> EvalRun:
    """Build a minimal EvalRun instance via the ORM constructor."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "test-run",
        "config_yaml": "eval:\n  model: gemini/gemini-2.5-flash-lite",
        "status": RunStatus.pending,
        "provider": "gemini",
        "model": "gemini-2.5-flash-lite",
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


def _make_result(**kwargs: object) -> EvalResult:
    """Build a minimal EvalResult instance via the ORM constructor."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "sample_index": 0,
        "input_text": "What is 2+2?",
        "model_output": "4",
        "expected_output": "4",
        "judge_scores": {},
        "tokens_used": 10,
        "latency_ms": 100.0,
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


# ── create_run ────────────────────────────────────────────────────────


async def test_create_run_adds_and_commits() -> None:
    session = _mock_session()

    async def _refresh(obj: EvalRun) -> None:
        obj.id = uuid.uuid4()
        obj.created_at = datetime.now(UTC)

    session.refresh.side_effect = _refresh

    run = await repos.create_run(
        session,
        name="my-run",
        config_yaml="eval:\n  model: gemini/x",
        provider="gemini",
        model="gemini-2.5-flash-lite",
    )

    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()
    assert run.status == RunStatus.pending
    assert run.name == "my-run"
    assert run.provider == "gemini"


# ── get_run ───────────────────────────────────────────────────────────


async def test_get_run_returns_run() -> None:
    run = _make_run()
    session = _mock_session()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = run
    session.execute = AsyncMock(return_value=scalar_result)

    result = await repos.get_run(session, cast(uuid.UUID, run.id))

    assert result is run


async def test_get_run_returns_none_when_missing() -> None:
    session = _mock_session()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=scalar_result)

    result = await repos.get_run(session, uuid.uuid4())

    assert result is None


# ── list_runs ─────────────────────────────────────────────────────────


async def test_list_runs_returns_all() -> None:
    runs = [_make_run(name="a"), _make_run(name="b")]
    session = _mock_session()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = runs
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=execute_result)

    result = await repos.list_runs(session)

    assert list(result) == runs


# ── update_run_status ─────────────────────────────────────────────────


async def test_update_run_status_to_running_sets_started_at() -> None:
    run = _make_run()
    session = _mock_session()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = run
    session.execute = AsyncMock(return_value=scalar_result)

    session.refresh = AsyncMock()

    updated = await repos.update_run_status(session, cast(uuid.UUID, run.id), RunStatus.running)

    assert updated.status == RunStatus.running
    assert updated.started_at is not None
    session.commit.assert_awaited_once()


async def test_update_run_status_to_completed_sets_completed_at() -> None:
    run = _make_run(status=RunStatus.running, started_at=datetime.now(UTC))
    session = _mock_session()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = run
    session.execute = AsyncMock(return_value=scalar_result)

    await repos.update_run_status(session, cast(uuid.UUID, run.id), RunStatus.completed)

    assert run.completed_at is not None


async def test_update_run_status_raises_when_not_found() -> None:
    session = _mock_session()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=scalar_result)

    with pytest.raises(ValueError, match="not found"):
        await repos.update_run_status(session, uuid.uuid4(), RunStatus.running)


async def test_update_run_status_sets_error_message() -> None:
    run = _make_run()
    session = _mock_session()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = run
    session.execute = AsyncMock(return_value=scalar_result)

    await repos.update_run_status(
        session,
        cast(uuid.UUID, run.id),
        RunStatus.failed,
        error_message="something broke",
    )

    assert run.error_message == "something broke"


# ── update_run_progress ───────────────────────────────────────────────


async def test_update_run_progress_updates_fields() -> None:
    run = _make_run()
    session = _mock_session()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = run
    session.execute = AsyncMock(return_value=scalar_result)

    await repos.update_run_progress(
        session,
        cast(uuid.UUID, run.id),
        total_samples=100,
        completed_samples=42,
        total_tokens=5000,
        total_latency_ms=3200.5,
        aggregate_scores={"faithfulness": 8.1},
    )

    assert run.total_samples == 100
    assert run.completed_samples == 42
    assert run.total_tokens == 5000
    assert run.total_latency_ms == 3200.5
    assert run.aggregate_scores == {"faithfulness": 8.1}


# ── save_result ───────────────────────────────────────────────────────


async def test_save_result_adds_and_returns() -> None:
    run_id = uuid.uuid4()
    session = _mock_session()

    async def _refresh(obj: EvalResult) -> None:
        obj.id = uuid.uuid4()

    session.refresh.side_effect = _refresh

    result = await repos.save_result(
        session,
        run_id=run_id,
        sample_index=0,
        input_text="What is 2+2?",
        status=ResultStatus.success,
        model_output="4",
        expected_output="4",
        judge_scores={"faithfulness": {"score": 9, "reasoning": "correct", "confidence": 0.95}},
        tokens_used=10,
        latency_ms=50.0,
    )

    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    assert result.run_id == run_id
    assert result.sample_index == 0
    assert result.status == ResultStatus.success


async def test_save_result_defaults_judge_scores_to_empty_dict() -> None:
    session = _mock_session()

    result = await repos.save_result(
        session,
        run_id=uuid.uuid4(),
        sample_index=1,
        input_text="hello",
        status=ResultStatus.error,
        error_message="timeout",
    )

    assert result.judge_scores == {}


# ── get_results_for_run ───────────────────────────────────────────────


async def test_get_results_for_run_returns_ordered_results() -> None:
    run_id = uuid.uuid4()
    results = [
        _make_result(run_id=run_id, sample_index=0),
        _make_result(run_id=run_id, sample_index=1),
    ]
    session = _mock_session()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = results
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=execute_result)

    fetched = await repos.get_results_for_run(session, run_id)

    assert list(fetched) == results
