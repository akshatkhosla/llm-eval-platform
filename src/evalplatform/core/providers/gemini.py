import asyncio
import os
import time

from google import genai
from google.genai import types

from evalplatform.core.providers.base import LLMResponse

SUPPORTED_MODELS = frozenset(
    {
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    }
)

_RATE_LIMIT_STATUS = 429
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1.0


def _is_rate_limit_error(exc: Exception) -> bool:
    # google-genai v1.x raises ClientError for 4xx; check status code or message
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == _RATE_LIMIT_STATUS:
        return True
    msg = str(exc).lower()
    return "429" in msg or "resource exhausted" in msg or "rate limit" in msg


class GeminiProvider:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_concurrency: int = 5,
    ) -> None:
        if model not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported Gemini model: {model!r}. Choose from {SUPPORTED_MODELS}")
        self._model = model
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def generate(
        self,
        prompt: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        t0 = time.monotonic()
        async with self._semaphore:
            response = await self._generate_with_backoff(prompt, config)
        latency_ms = (time.monotonic() - t0) * 1000

        text = response.text or ""
        usage = response.usage_metadata
        return LLMResponse(
            text=text,
            input_tokens=usage.prompt_token_count or 0,
            output_tokens=usage.candidates_token_count or 0,
            latency_ms=latency_ms,
            model=self._model,
            provider="gemini",
        )

    async def _generate_with_backoff(
        self,
        prompt: str,
        config: types.GenerateContentConfig,
    ) -> object:
        delay = _INITIAL_BACKOFF
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
                return response
            except Exception as exc:
                last_exc = exc
                if _is_rate_limit_error(exc) and attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    # Expose model/provider name for introspection
    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "gemini"
