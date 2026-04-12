from functools import lru_cache

from evalplatform.core.providers.base import BaseLLMProvider
from evalplatform.core.providers.gemini import GeminiProvider
from evalplatform.core.providers.ollama import OllamaProvider

_PROVIDERS = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


@lru_cache(maxsize=32)
def get_provider(provider_name: str, model: str) -> BaseLLMProvider:
    """Return a cached provider instance for *provider_name* configured to use *model*.

    Results are cached so repeated calls with the same arguments return the same
    instance, avoiding redundant API client construction and semaphore creation.

    Args:
        provider_name: One of "gemini" or "ollama".
        model: The model identifier (e.g. "gemini-2.5-flash" or "llama3").

    Raises:
        ValueError: If *provider_name* is not recognised.
    """
    cls = _PROVIDERS.get(provider_name)
    if cls is None:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ValueError(f"Unknown provider {provider_name!r}. Supported providers: {supported}")
    return cls(model=model)  # type: ignore[call-arg]
