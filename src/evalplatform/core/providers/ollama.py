import asyncio
import time

import httpx

from evalplatform.core.providers.base import LLMResponse

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider:
    def __init__(
        self,
        model: str,
        base_url: str = _DEFAULT_BASE_URL,
        max_concurrency: int = 20,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout

    async def generate(
        self,
        prompt: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        t0 = time.monotonic()
        async with self._semaphore, httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
            )
        latency_ms = (time.monotonic() - t0) * 1000

        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"Ollama returned no choices for model {self._model!r}")
        message = choices[0].get("message") or {}
        text: str = message.get("content") or ""
        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            model=self._model,
            provider="ollama",
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "ollama"
