"""Pydantic models for eval configuration and results."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ── Judge configs (discriminated union) ──────────────────────────────


class LLMJudgeConfig(BaseModel):
    type: Literal["llm"] = "llm"
    model: str  # "provider/model-name"
    rubric: str


class ContainsKeywordJudgeConfig(BaseModel):
    type: Literal["contains_keyword"] = "contains_keyword"
    keyword: str
    case_sensitive: bool = False


class RegexMatchJudgeConfig(BaseModel):
    type: Literal["regex_match"] = "regex_match"
    pattern: str


JudgeConfig = Annotated[
    LLMJudgeConfig | ContainsKeywordJudgeConfig | RegexMatchJudgeConfig,
    Field(discriminator="type"),
]


# ── Provider config ──────────────────────────────────────────────────


class ProviderConfig(BaseModel):
    base_url: str | None = None
    max_concurrency: int = 10


# ── Top-level eval config ────────────────────────────────────────────


class EvalConfig(BaseModel):
    model: str  # "provider/model-name"
    dataset: str  # path to JSONL file
    timeout_seconds: int = 30
    judges: list[JudgeConfig] = Field(min_length=1)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    max_concurrency: int = 10


# ── Result models ────────────────────────────────────────────────────


class JudgeResultStatus(StrEnum):
    ok = "ok"
    error = "error"


class JudgeResult(BaseModel):
    judge_type: str
    judge_index: int
    score: int | None = None
    reasoning: str = ""
    status: JudgeResultStatus = JudgeResultStatus.ok
    error: str | None = None


class SampleStatus(StrEnum):
    passed = "passed"
    error = "error"
    partial = "partial"


class SampleResult(BaseModel):
    row_index: int
    prompt: str
    expected: str | None = None
    response: str | None = None
    status: SampleStatus = SampleStatus.passed
    error: str | None = None
    judge_results: list[JudgeResult] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class AggregateScore(BaseModel):
    mean: float
    min_score: int
    max_score: int
    count: int


class EvalRunResult(BaseModel):
    total_rows: int
    completed_rows: int
    error_rows: int
    sample_results: list[SampleResult]
    aggregate_scores: dict[int, AggregateScore] = Field(default_factory=dict)
