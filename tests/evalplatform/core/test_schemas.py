"""Tests for eval Pydantic schemas."""

import pytest
from pydantic import ValidationError

from evalplatform.core.schemas import (
    AggregateScore,
    ContainsKeywordJudgeConfig,
    EvalConfig,
    EvalRunResult,
    JudgeResult,
    JudgeResultStatus,
    LLMJudgeConfig,
    RegexMatchJudgeConfig,
    SampleResult,
    SampleStatus,
)


class TestJudgeConfigDiscriminator:
    def test_llm_judge_config(self) -> None:
        cfg = LLMJudgeConfig(model="gemini/gemini-2.5-flash", rubric="Is it accurate?")
        assert cfg.type == "llm"
        assert cfg.model == "gemini/gemini-2.5-flash"

    def test_contains_keyword_config(self) -> None:
        cfg = ContainsKeywordJudgeConfig(keyword="python")
        assert cfg.type == "contains_keyword"
        assert cfg.case_sensitive is False

    def test_regex_match_config(self) -> None:
        cfg = RegexMatchJudgeConfig(pattern=r"^\d+$")
        assert cfg.type == "regex_match"

    def test_discriminated_union_in_eval_config(self) -> None:
        config = EvalConfig(
            model="gemini/gemini-2.5-flash",
            dataset="data/test.jsonl",
            judges=[
                {"type": "llm", "model": "gemini/gemini-2.5-pro", "rubric": "Good?"},
                {"type": "contains_keyword", "keyword": "hello"},
                {"type": "regex_match", "pattern": "^[A-Z]"},
            ],
        )
        assert isinstance(config.judges[0], LLMJudgeConfig)
        assert isinstance(config.judges[1], ContainsKeywordJudgeConfig)
        assert isinstance(config.judges[2], RegexMatchJudgeConfig)


class TestEvalConfig:
    def test_defaults(self) -> None:
        config = EvalConfig(
            model="ollama/llama3",
            dataset="data/test.jsonl",
            judges=[{"type": "contains_keyword", "keyword": "test"}],
        )
        assert config.timeout_seconds == 30
        assert config.max_concurrency == 10
        assert config.providers == {}

    def test_empty_judges_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EvalConfig(
                model="ollama/llama3",
                dataset="data/test.jsonl",
                judges=[],
            )


class TestResultModels:
    def test_judge_result_ok(self) -> None:
        jr = JudgeResult(judge_type="llm", judge_index=0, score=8, reasoning="Good answer")
        assert jr.status == JudgeResultStatus.ok
        assert jr.error is None

    def test_judge_result_error(self) -> None:
        jr = JudgeResult(
            judge_type="llm",
            judge_index=0,
            status=JudgeResultStatus.error,
            error="timeout",
        )
        assert jr.score is None

    def test_sample_result_defaults(self) -> None:
        sr = SampleResult(row_index=0, prompt="hi")
        assert sr.status == SampleStatus.passed
        assert sr.judge_results == []

    def test_eval_run_result(self) -> None:
        result = EvalRunResult(
            total_rows=10,
            completed_rows=10,
            error_rows=1,
            sample_results=[],
            aggregate_scores={
                0: AggregateScore(mean=7.5, min_score=3, max_score=10, count=9),
            },
        )
        assert result.aggregate_scores[0].mean == 7.5
