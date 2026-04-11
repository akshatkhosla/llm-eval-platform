from evalplatform.core.providers.base import BaseLLMProvider
from evalplatform.core.providers.gemini import GeminiProvider
from evalplatform.core.providers.ollama import OllamaProvider

_PROVIDERS = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def get_provider(provider_name: str, model: str) -> BaseLLMProvider:
    """Return a provider instance for *provider_name* configured to use *model*.

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
