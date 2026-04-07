"""Tests for the async eval runner."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from evalplatform.core.providers.base import LLMResponse
from evalplatform.core.runner import _compute_aggregates, _load_dataset, run_eval
from evalplatform.core.schemas import (
    ContainsKeywordJudgeConfig,
    EvalConfig,
    JudgeResult,
    JudgeResultStatus,
    RegexMatchJudgeConfig,
    SampleResult,
    SampleStatus,
)


# ── _load_dataset ────────────────────────────────────────────────────


class TestLoadDataset:
    def test_loads_valid_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text(
            json.dumps({"prompt": "hi", "expected": "hello"})
            + "\n"
            + json.dumps({"prompt": "bye"})
            + "\n"
        )
        rows = _load_dataset(p)
        assert len(rows) == 2
        assert rows[0]["prompt"] == "hi"
        assert rows[1]["prompt"] == "bye"

    def test_skips_rows_without_prompt(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text(json.dumps({"expected": "no prompt"}) + "\n")
        rows = _load_dataset(p)
        assert len(rows) == 0

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text("not json\n" + json.dumps({"prompt": "ok"}) + "\n")
        rows = _load_dataset(p)
        assert len(rows) == 1

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text("\n" + json.dumps({"prompt": "ok"}) + "\n\n")
        rows = _load_dataset(p)
        assert len(rows) == 1


# ── _compute_aggregates ──────────────────────────────────────────────


class TestComputeAggregates:
    def test_basic_aggregation(self) -> None:
        samples = [
            SampleResult(
                row_index=0,
                prompt="a",
                judge_results=[
                    JudgeResult(judge_type="kw", judge_index=0, score=10),
                    JudgeResult(judge_type="kw", judge_index=1, score=0),
                ],
            ),
            SampleResult(
                row_index=1,
                prompt="b",
                judge_results=[
                    JudgeResult(judge_type="kw", judge_index=0, score=0),
                    JudgeResult(judge_type="kw", judge_index=1, score=10),
                ],
            ),
        ]
        agg = _compute_aggregates(samples)
        assert agg[0].mean == 5.0
        assert agg[0].min_score == 0
        assert agg[0].max_score == 10
        assert agg[1].mean == 5.0

    def test_skips_error_results(self) -> None:
        samples = [
            SampleResult(
                row_index=0,
                prompt="a",
                judge_results=[
                    JudgeResult(
                        judge_type="llm",
                        judge_index=0,
                        status=JudgeResultStatus.error,
                        error="fail",
                    ),
                ],
            ),
        ]
        agg = _compute_aggregates(samples)
        assert 0 not in agg


# ── run_eval (integration with mocked provider) ─────────────────────


def _make_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=5,
        output_tokens=10,
        latency_ms=50.0,
        model="test",
        provider="test",
    )


class TestRunEval:
    @pytest.fixture()
    def dataset_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "test.jsonl"
        p.write_text(
            json.dumps({"prompt": "Say python", "expected": "python"})
            + "\n"
            + json.dumps({"prompt": "Start with capital"})
            + "\n"
        )
        return p

    async def test_deterministic_judges_only(self, dataset_path: Path) -> None:
        config = EvalConfig(
            model="ollama/llama3",
            dataset=str(dataset_path),
            judges=[
                ContainsKeywordJudgeConfig(keyword="python"),
                RegexMatchJudgeConfig(pattern=r"^[A-Z]"),
            ],
        )

        mock_provider = AsyncMock()
        # Both rows get the same response containing "python" and starting uppercase
        mock_provider.generate.return_value = _make_llm_response("Python is great")

        with patch("evalplatform.core.runner.get_provider", return_value=mock_provider):
            result = await run_eval(config)

        assert result.total_rows == 2
        assert result.completed_rows == 2
        assert result.error_rows == 0

        r0 = result.sample_results[0]
        assert r0.status == SampleStatus.passed
        assert r0.judge_results[0].score == 10  # contains "python"
        assert r0.judge_results[1].score == 10  # starts with capital "P"

    async def test_model_failure_marks_error(self, dataset_path: Path) -> None:
        config = EvalConfig(
            model="ollama/llama3",
            dataset=str(dataset_path),
            judges=[ContainsKeywordJudgeConfig(keyword="test")],
        )

        mock_provider = AsyncMock()
        mock_provider.generate.side_effect = ConnectionError("offline")

        with patch("evalplatform.core.runner.get_provider", return_value=mock_provider):
            result = await run_eval(config)

        assert result.error_rows == 2
        for sr in result.sample_results:
            assert sr.status == SampleStatus.error

    async def test_status_callback_invoked(self, dataset_path: Path) -> None:
        config = EvalConfig(
            model="ollama/llama3",
            dataset=str(dataset_path),
            judges=[ContainsKeywordJudgeConfig(keyword="x")],
        )

        mock_provider = AsyncMock()
        mock_provider.generate.return_value = _make_llm_response("x marks the spot")
        callback = AsyncMock()

        with patch("evalplatform.core.runner.get_provider", return_value=mock_provider):
            await run_eval(config, status_callback=callback)

        assert callback.call_count == 2
        # Each call should be (completed, total)
        for call_args in callback.call_args_list:
            completed, total = call_args[0]
            assert total == 2
            assert 1 <= completed <= 2
