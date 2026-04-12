"""Tests for the evalplatform CLI."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from typer.testing import CliRunner

from evalplatform.cli import app

runner = CliRunner()

# ── Helpers / fixtures ─────────────────────────────────────────────────

RUN_ID = str(uuid.uuid4())
RUN_ID_B = str(uuid.uuid4())

SUMMARY = {
    "run_id": RUN_ID,
    "name": "test-run",
    "status": "completed",
    "provider": "gemini",
    "model": "gemini-1.5-flash",
    "created_at": "2026-01-01T12:00:00Z",
    "started_at": "2026-01-01T12:00:01Z",
    "completed_at": "2026-01-01T12:00:10Z",
    "total_samples": 2,
    "completed_samples": 2,
    "total_tokens": 100,
    "total_latency_ms": 500.0,
}

DETAIL = {
    **SUMMARY,
    "error_message": None,
    "aggregate_scores": {"contains_keyword": {"mean": 1.0}},
    "config_yaml": "eval:\n  model: gemini/gemini-1.5-flash\n",
}

RESULTS_RESPONSE = {
    "run_id": RUN_ID,
    "results": [
        {
            "id": str(uuid.uuid4()),
            "sample_index": 0,
            "input_text": "What is Python?",
            "model_output": "A programming language.",
            "expected_output": "python",
            "judge_scores": {"contains_keyword": {"score": 1.0, "status": "pass"}},
            "tokens_used": 50,
            "latency_ms": 250.0,
            "status": "completed",
            "error_message": None,
        },
        {
            "id": str(uuid.uuid4()),
            "sample_index": 1,
            "input_text": "Say hello.",
            "model_output": "Hello!",
            "expected_output": "hello",
            "judge_scores": {"contains_keyword": {"score": 0.0, "status": "fail"}},
            "tokens_used": 10,
            "latency_ms": 100.0,
            "status": "completed",
            "error_message": None,
        },
    ],
}

COMPARE_RESPONSE = {
    "run_id_a": RUN_ID,
    "run_id_b": RUN_ID_B,
    "run_a": {**SUMMARY, "run_id": RUN_ID},
    "run_b": {**SUMMARY, "run_id": RUN_ID_B, "name": "test-run-b"},
    "judge_summaries": [
        {"judge_key": "contains_keyword", "mean_a": 0.8, "mean_b": 0.9, "delta": 0.1}
    ],
    "samples": [],
    "flagged_samples": [],
}


def _mock_response(data: object, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = status_code < 400
    resp.json.return_value = data
    resp.text = json.dumps(data)
    return resp


# ── run command ───────────────────────────────────────────────────────


def test_run_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(tmp_path / "missing.yaml")])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_run_submit_no_wait(tmp_path: Path) -> None:
    config = tmp_path / "eval.yaml"
    config.write_text("eval:\n  model: gemini/gemini-1.5-flash\n")

    submit_resp = _mock_response({"run_id": RUN_ID, "status": "pending"}, 202)

    with patch("evalplatform.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = submit_resp
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["run", str(config)])

    assert result.exit_code == 0
    assert RUN_ID in result.output


def test_run_submit_failure(tmp_path: Path) -> None:
    config = tmp_path / "eval.yaml"
    config.write_text("eval:\n  model: gemini/gemini-1.5-flash\n")

    err_resp = _mock_response({"detail": "Bad config"}, 400)

    with patch("evalplatform.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = err_resp
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["run", str(config)])

    assert result.exit_code == 1


# ── status command ────────────────────────────────────────────────────


def test_status_found() -> None:
    with patch("evalplatform.cli._api_get", return_value=DETAIL) as mock_get:
        result = runner.invoke(app, ["status", RUN_ID])

    mock_get.assert_called_once_with(f"/api/v1/evals/{RUN_ID}")
    assert result.exit_code == 0
    assert "test-run" in result.output
    assert "completed" in result.output
    assert "gemini" in result.output


def test_status_not_found() -> None:
    with patch("evalplatform.cli._api_get", side_effect=SystemExit(1)):
        result = runner.invoke(app, ["status", RUN_ID])
    assert result.exit_code != 0


# ── results command ───────────────────────────────────────────────────


def test_results_table() -> None:
    with patch("evalplatform.cli._api_get", return_value=RESULTS_RESPONSE):
        result = runner.invoke(app, ["results", RUN_ID])
    assert result.exit_code == 0
    assert "contains_keyword" in result.output
    assert "1.00" in result.output


def test_results_json() -> None:
    with patch("evalplatform.cli._api_get", return_value=RESULTS_RESPONSE):
        result = runner.invoke(app, ["results", RUN_ID, "--format", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["run_id"] == RUN_ID
    assert len(parsed["results"]) == 2


def test_results_empty() -> None:
    with patch("evalplatform.cli._api_get", return_value={"run_id": RUN_ID, "results": []}):
        result = runner.invoke(app, ["results", RUN_ID])
    assert result.exit_code == 0
    assert "no results" in result.output.lower()


# ── compare command ───────────────────────────────────────────────────


def test_compare() -> None:
    with patch("evalplatform.cli._api_get", return_value=COMPARE_RESPONSE) as mock_get:
        result = runner.invoke(app, ["compare", RUN_ID, RUN_ID_B])

    mock_get.assert_called_once_with("/api/v1/evals/compare", run_ids=f"{RUN_ID},{RUN_ID_B}")
    assert result.exit_code == 0
    assert "contains_keyword" in result.output
    assert "0.800" in result.output
    assert "0.900" in result.output
    assert "+0.100" in result.output


def test_compare_negative_delta() -> None:
    response = {
        **COMPARE_RESPONSE,
        "judge_summaries": [{"judge_key": "quality", "mean_a": 0.9, "mean_b": 0.7, "delta": -0.2}],
    }
    with patch("evalplatform.cli._api_get", return_value=response):
        result = runner.invoke(app, ["compare", RUN_ID, RUN_ID_B])
    assert result.exit_code == 0
    assert "-0.200" in result.output


# ── list command ──────────────────────────────────────────────────────


def test_list_runs() -> None:
    with patch("evalplatform.cli._api_get", return_value=[SUMMARY]) as mock_get:
        result = runner.invoke(app, ["list"])

    mock_get.assert_called_once_with("/api/v1/evals", status=None, limit=10)
    assert result.exit_code == 0
    assert "test-run" in result.output
    # Rich may truncate cell values at narrow terminal widths; check prefix
    assert "complet" in result.output


def test_list_runs_with_filters() -> None:
    with patch("evalplatform.cli._api_get", return_value=[SUMMARY]) as mock_get:
        result = runner.invoke(app, ["list", "--status", "completed", "--limit", "5"])

    mock_get.assert_called_once_with("/api/v1/evals", status="completed", limit=5)
    assert result.exit_code == 0


def test_list_runs_empty() -> None:
    with patch("evalplatform.cli._api_get", return_value=[]):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "no eval runs" in result.output.lower()


# ── error handling (via CLI runner) ──────────────────────────────────


def test_status_api_returns_404() -> None:
    """status command exits non-zero when the API returns 404."""
    not_found = _mock_response({"detail": "Run not found"}, 404)
    with patch("evalplatform.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = not_found
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["status", RUN_ID])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_status_api_server_error() -> None:
    """status command exits non-zero on a 5xx response."""
    err = _mock_response({"detail": "Internal Server Error"}, 500)
    with patch("evalplatform.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = err
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["status", RUN_ID])

    assert result.exit_code == 1
    assert "500" in result.output
