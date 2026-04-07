"""Judge implementations for scoring LLM responses."""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from evalplatform.core.providers.base import BaseLLMProvider
from evalplatform.core.schemas import JudgeResult, JudgeResultStatus

logger = logging.getLogger(__name__)

# ── Protocol ─────────────────────────────────────────────────────────


class BaseJudge(Protocol):
    async def judge(
        self,
        prompt: str,
        output: str,
        expected: str | None,
    ) -> JudgeResult: ...


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
