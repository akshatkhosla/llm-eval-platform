"""Judge implementations for scoring LLM responses."""

from __future__ import annotations

import json
import logging
import re
from typing import ClassVar, Protocol

from evalplatform.core.providers.base import BaseLLMProvider
from evalplatform.core.schemas import JudgeResult, JudgeResultStatus

logger = logging.getLogger(__name__)

# ── Protocol ─────────────────────────────────────────────────────────


class BaseJudge(Protocol):
    """Protocol that all judge implementations must satisfy."""

    async def judge(
        self,
        prompt: str,
        output: str,
        expected: str | None,
    ) -> JudgeResult:
        """Score *output* given the original *prompt* and optional *expected* answer."""
        ...


# ── LLM Judge ────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an impartial evaluator. Given a prompt, expected answer, and "
    "model response, score the response 0\u201310 based on the rubric.\n"
    'Return ONLY valid JSON: {"score": <int 0-10>, "reasoning": "<string>"}'
)


def _build_user_prompt(
    rubric: str,
    prompt: str,
    response: str,
    expected: str | None,
) -> str:
    parts = [
        f"Rubric: {rubric}",
        f"Prompt: {prompt}",
    ]
    if expected is not None:
        parts.append(f"Expected: {expected}")
    parts.append(f"Response: {response}")
    return "\n".join(parts)


def _parse_judge_json(text: str) -> dict[str, object]:
    """Extract the first JSON object from *text*."""
    # Try the full text first, then fall back to regex extraction.
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())  # type: ignore[no-any-return]
    raise json.JSONDecodeError("No JSON object found", text, 0)


class LLMJudge:
    """Scores responses 0–10 using an LLM with a user-supplied rubric."""

    def __init__(
        self,
        provider: BaseLLMProvider,
        rubric: str,
        judge_index: int,
    ) -> None:
        self._provider = provider
        self._rubric = rubric
        self._judge_index = judge_index

    async def judge(
        self,
        prompt: str,
        output: str,
        expected: str | None,
    ) -> JudgeResult:
        user_msg = _build_user_prompt(self._rubric, prompt, output, expected)
        max_attempts = 2
        last_err = ""

        for attempt in range(max_attempts):
            try:
                llm_resp = await self._provider.generate(
                    prompt=user_msg,
                    system=_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=512,
                )
                parsed = _parse_judge_json(llm_resp.text)
                score = int(parsed["score"])
                reasoning = str(parsed.get("reasoning", ""))
                return JudgeResult(
                    judge_type="llm",
                    judge_index=self._judge_index,
                    score=score,
                    reasoning=reasoning,
                )
            except Exception as exc:
                last_err = f"attempt {attempt + 1}: {exc}"
                logger.warning("LLMJudge error: %s", last_err)

        return JudgeResult(
            judge_type="llm",
            judge_index=self._judge_index,
            status=JudgeResultStatus.error,
            error=last_err,
        )


# ── Deterministic judges ─────────────────────────────────────────────


class ContainsKeywordJudge:
    """Deterministic judge: scores 10 if a keyword appears in the output, 0 otherwise."""

    def __init__(self, keyword: str, case_sensitive: bool, judge_index: int) -> None:
        self._keyword = keyword
        self._case_sensitive = case_sensitive
        self._judge_index = judge_index

    async def judge(
        self,
        prompt: str,
        output: str,
        expected: str | None,
    ) -> JudgeResult:
        if self._case_sensitive:
            found = self._keyword in output
        else:
            found = self._keyword.lower() in output.lower()
        return JudgeResult(
            judge_type="contains_keyword",
            judge_index=self._judge_index,
            score=10 if found else 0,
            reasoning=f"Keyword {'found' if found else 'not found'}: {self._keyword!r}",
        )


class RegexMatchJudge:
    """Deterministic judge: scores 10 if a regex pattern matches the output, 0 otherwise."""

    def __init__(self, pattern: str, judge_index: int) -> None:
        self._pattern = re.compile(pattern)
        self._judge_index = judge_index

    async def judge(
        self,
        prompt: str,
        output: str,
        expected: str | None,
    ) -> JudgeResult:
        matched = self._pattern.search(output) is not None
        return JudgeResult(
            judge_type="regex_match",
            judge_index=self._judge_index,
            score=10 if matched else 0,
            reasoning=f"Pattern {'matched' if matched else 'did not match'}: {self._pattern.pattern!r}",
        )


# ── Specialized LLM judges ────────────────────────────────────────────

_STRICTER_SUFFIX = (
    "\n\nCRITICAL: Your entire response must be a single valid JSON object. "
    "No markdown fences, no prose, no explanation — only the raw JSON."
)

_DEFAULT_SCORE = 3  # middle of 1-5 scale; used when all attempts fail


class _SpecializedLLMJudge:
    """Shared retry/fallback logic for FaithfulnessJudge, RelevanceJudge, CoherenceJudge.

    Subclasses must define ``_judge_type`` and ``_system_prompt`` as class
    variables, and override ``_build_user_prompt`` and ``_parse_llm_response``.
    """

    _judge_type: ClassVar[str]
    _system_prompt: ClassVar[str]

    def __init__(self, provider: BaseLLMProvider, judge_index: int) -> None:
        self._provider = provider
        self._judge_index = judge_index

    @property
    def judge_index(self) -> int:
        return self._judge_index

    def _build_user_prompt(self, prompt: str, output: str, expected: str | None) -> str:
        raise NotImplementedError

    def _parse_llm_response(self, parsed: dict[str, object]) -> JudgeResult:
        raise NotImplementedError

    async def judge(
        self,
        prompt: str,
        output: str,
        expected: str | None,
    ) -> JudgeResult:
        user_msg = self._build_user_prompt(prompt, output, expected)

        # ── Attempt 1: normal system prompt ──────────────────────────
        try:
            llm_resp = await self._provider.generate(
                prompt=user_msg,
                system=self._system_prompt,
                temperature=0.0,
                max_tokens=512,
            )
            parsed = _parse_judge_json(llm_resp.text)
            return self._parse_llm_response(parsed)
        except Exception as exc:
            logger.warning("%s attempt 1 failed: %s", self.__class__.__name__, exc)

        # ── Attempt 2: stricter system prompt ─────────────────────────
        stricter = self._system_prompt + _STRICTER_SUFFIX
        try:
            llm_resp = await self._provider.generate(
                prompt=user_msg,
                system=stricter,
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as exc:
            logger.warning("%s attempt 2 (LLM call) failed: %s", self.__class__.__name__, exc)
            # Deterministic fallback: both LLM calls raised an exception.
            return JudgeResult(
                judge_type=self._judge_type,
                judge_index=self._judge_index,
                score=_DEFAULT_SCORE,
                reasoning="Deterministic fallback: all LLM calls failed",
                status=JudgeResultStatus.error,
                error=str(exc),
            )

        try:
            parsed = _parse_judge_json(llm_resp.text)
            return self._parse_llm_response(parsed)
        except Exception:
            # JSON still unparseable after stricter prompt → parse_failed fallback.
            return JudgeResult(
                judge_type=self._judge_type,
                judge_index=self._judge_index,
                score=_DEFAULT_SCORE,
                reasoning="JSON parsing failed after retry; using default score",
                parse_failed=True,
            )


# ── FaithfulnessJudge ─────────────────────────────────────────────────

_FAITHFULNESS_SYSTEM = """\
You are an expert faithfulness evaluator. Assess whether the model output is
grounded in the provided context (the expected/reference text).

Scoring rubric (1–5):
  5 – Fully faithful: every claim is directly supported by the context; no hallucinations.
  4 – Mostly faithful: minor reasonable inferences; core claims are grounded.
  3 – Partially faithful: some claims supported, but notable unsupported claims present.
  2 – Largely unfaithful: most claims lack support; significant hallucination.
  1 – Completely unfaithful: output contradicts the context or is entirely hallucinated.

Penalise hallucination heavily. Reward direct citation or close paraphrase.

Return ONLY valid JSON:
{"score": <int 1-5>, "reasoning": "<string>", "confidence": <float 0-1>, "specific_issues": ["<issue>", ...]}\
"""


class FaithfulnessJudge(_SpecializedLLMJudge):
    _judge_type: ClassVar[str] = "faithfulness"
    _system_prompt: ClassVar[str] = _FAITHFULNESS_SYSTEM

    def _build_user_prompt(self, prompt: str, output: str, expected: str | None) -> str:
        parts = [f"Question: {prompt}"]
        if expected is not None:
            parts.append(f"Reference context: {expected}")
        parts.append(f"Model output: {output}")
        return "\n".join(parts)

    def _parse_llm_response(self, parsed: dict[str, object]) -> JudgeResult:
        score = int(parsed["score"])
        reasoning = str(parsed.get("reasoning", ""))
        confidence_raw = parsed.get("confidence")
        confidence = float(confidence_raw) if confidence_raw is not None else None
        specific_issues = [str(s) for s in parsed.get("specific_issues", [])]
        return JudgeResult(
            judge_type=self._judge_type,
            judge_index=self._judge_index,
            score=score,
            reasoning=reasoning,
            confidence=confidence,
            specific_issues=specific_issues,
        )


# ── RelevanceJudge ────────────────────────────────────────────────────

_RELEVANCE_SYSTEM = """\
You are an expert relevance evaluator. Assess whether the model output actually
addresses the question asked.

Scoring rubric (1–5):
  5 – Highly relevant: output directly and completely addresses the question.
  4 – Mostly relevant: addresses the main question with minor tangents.
  3 – Partially relevant: partially addresses the question or misses key aspects.
  2 – Mostly irrelevant: barely addresses the question; mostly tangential.
  1 – Completely irrelevant: output does not address the question at all.

Penalise tangential or off-topic answers. Reward directness and completeness.

Return ONLY valid JSON:
{"score": <int 1-5>, "reasoning": "<string>", "confidence": <float 0-1>}\
"""


class RelevanceJudge(_SpecializedLLMJudge):
    _judge_type: ClassVar[str] = "relevance"
    _system_prompt: ClassVar[str] = _RELEVANCE_SYSTEM

    def _build_user_prompt(self, prompt: str, output: str, expected: str | None) -> str:
        parts = [f"Question: {prompt}", f"Model output: {output}"]
        if expected is not None:
            parts.append(f"Expected answer (for reference): {expected}")
        return "\n".join(parts)

    def _parse_llm_response(self, parsed: dict[str, object]) -> JudgeResult:
        score = int(parsed["score"])
        reasoning = str(parsed.get("reasoning", ""))
        confidence_raw = parsed.get("confidence")
        confidence = float(confidence_raw) if confidence_raw is not None else None
        return JudgeResult(
            judge_type=self._judge_type,
            judge_index=self._judge_index,
            score=score,
            reasoning=reasoning,
            confidence=confidence,
        )


# ── CoherenceJudge ────────────────────────────────────────────────────

_COHERENCE_SYSTEM = """\
You are an expert coherence evaluator. Assess whether the model output is
logically consistent and well-structured.

Scoring rubric (1–5):
  5 – Highly coherent: logically consistent, well-structured, clear flow, complete.
  4 – Mostly coherent: minor logical gaps; generally well-structured and consistent.
  3 – Partially coherent: some inconsistencies or structural issues; mostly followable.
  2 – Mostly incoherent: significant contradictions or poor structure.
  1 – Incoherent: contradictory, disorganised, or incomprehensible.

Check for internal contradictions, logical flow, and completeness.

Return ONLY valid JSON:
{"score": <int 1-5>, "reasoning": "<string>", "confidence": <float 0-1>}\
"""


class CoherenceJudge(_SpecializedLLMJudge):
    _judge_type: ClassVar[str] = "coherence"
    _system_prompt: ClassVar[str] = _COHERENCE_SYSTEM

    def _build_user_prompt(self, prompt: str, output: str, expected: str | None) -> str:
        parts = [f"Question: {prompt}", f"Model output: {output}"]
        return "\n".join(parts)

    def _parse_llm_response(self, parsed: dict[str, object]) -> JudgeResult:
        score = int(parsed["score"])
        reasoning = str(parsed.get("reasoning", ""))
        confidence_raw = parsed.get("confidence")
        confidence = float(confidence_raw) if confidence_raw is not None else None
        return JudgeResult(
            judge_type=self._judge_type,
            judge_index=self._judge_index,
            score=score,
            reasoning=reasoning,
            confidence=confidence,
        )
