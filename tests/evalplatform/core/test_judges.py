"""Tests for judge implementations."""

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from evalplatform.core.judges import (
    ContainsKeywordJudge,
    LLMJudge,
    RegexMatchJudge,
    _parse_judge_json,
)
from evalplatform.core.providers.base import LLMResponse
from evalplatform.core.schemas import JudgeResultStatus


# ── Helpers ──────────────────────────────────────────────────────────


def _make_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=10,
        output_tokens=20,
        latency_ms=100.0,
        model="test-model",
        provider="test",
    )


# ── _parse_judge_json ────────────────────────────────────────────────


class TestParseJudgeJson:
    def test_plain_json(self) -> None:
        result = _parse_judge_json('{"score": 8, "reasoning": "good"}')
        assert result["score"] == 8

    def test_json_embedded_in_text(self) -> None:
        result = _parse_judge_json('Here is my answer: {"score": 5, "reasoning": "ok"} done')
        assert result["score"] == 5

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_judge_json("no json here")


# ── LLMJudge ─────────────────────────────────────────────────────────


class TestLLMJudge:
    async def test_successful_judge(self) -> None:
        provider = AsyncMock()
        provider.generate.return_value = _make_llm_response(
            '{"score": 7, "reasoning": "Solid answer"}'
        )
        judge = LLMJudge(provider=provider, rubric="Is it correct?", judge_index=0)
        result = await judge.judge("What is 2+2?", "4", "4")
        assert result.score == 7
        assert result.reasoning == "Solid answer"
        assert result.status == JudgeResultStatus.ok

    async def test_retry_on_bad_json(self) -> None:
        provider = AsyncMock()
        provider.generate.side_effect = [
            _make_llm_response("not json"),
            _make_llm_response('{"score": 9, "reasoning": "retry worked"}'),
        ]
        judge = LLMJudge(provider=provider, rubric="test", judge_index=1)
        result = await judge.judge("q", "a", None)
        assert result.score == 9
        assert provider.generate.call_count == 2

    async def test_error_after_all_retries(self) -> None:
        provider = AsyncMock()
        provider.generate.side_effect = [
            _make_llm_response("bad"),
            _make_llm_response("still bad"),
        ]
        judge = LLMJudge(provider=provider, rubric="test", judge_index=0)
        result = await judge.judge("q", "a", None)
        assert result.status == JudgeResultStatus.error
        assert result.error is not None

    async def test_error_on_provider_exception(self) -> None:
        provider = AsyncMock()
        provider.generate.side_effect = ConnectionError("network down")
        judge = LLMJudge(provider=provider, rubric="test", judge_index=0)
        result = await judge.judge("q", "a", None)
        assert result.status == JudgeResultStatus.error


# ── ContainsKeywordJudge ─────────────────────────────────────────────


class TestContainsKeywordJudge:
    async def test_keyword_found_case_insensitive(self) -> None:
        judge = ContainsKeywordJudge(keyword="Python", case_sensitive=False, judge_index=0)
        result = await judge.judge("q", "I love python programming", None)
        assert result.score == 10

    async def test_keyword_not_found(self) -> None:
        judge = ContainsKeywordJudge(keyword="java", case_sensitive=False, judge_index=0)
        result = await judge.judge("q", "I love python", None)
        assert result.score == 0

    async def test_case_sensitive(self) -> None:
        judge = ContainsKeywordJudge(keyword="Python", case_sensitive=True, judge_index=0)
        result = await judge.judge("q", "python is great", None)
        assert result.score == 0


# ── RegexMatchJudge ──────────────────────────────────────────────────


class TestRegexMatchJudge:
    async def test_pattern_matches(self) -> None:
        judge = RegexMatchJudge(pattern=r"^\d+$", judge_index=0)
        result = await judge.judge("q", "42", None)
        assert result.score == 10

    async def test_pattern_no_match(self) -> None:
        judge = RegexMatchJudge(pattern=r"^\d+$", judge_index=0)
        result = await judge.judge("q", "hello", None)
        assert result.score == 0

    async def test_partial_match(self) -> None:
        judge = RegexMatchJudge(pattern=r"^[A-Z]", judge_index=0)
        result = await judge.judge("q", "Hello world", None)
        assert result.score == 10
