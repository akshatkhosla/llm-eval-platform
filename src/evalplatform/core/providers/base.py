from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    """Normalised response returned by every LLM provider."""

    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model: str
    provider: str


@runtime_checkable
class BaseLLMProvider(Protocol):
    """Protocol that all LLM provider implementations must satisfy."""

    async def generate(
        self,
        prompt: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Call the underlying model and return a normalised LLMResponse."""
        ...
