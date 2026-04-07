"""Tests for the provider factory."""

from unittest.mock import patch

import pytest

from evalplatform.core.providers.factory import get_provider
from evalplatform.core.providers.gemini import GeminiProvider
from evalplatform.core.providers.ollama import OllamaProvider


def test_get_provider_gemini():
    with patch("google.genai.Client"), patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        provider = get_provider("gemini", "gemini-2.5-flash")
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-2.5-flash"
    assert provider.provider == "gemini"


def test_get_provider_ollama():
    provider = get_provider("ollama", "llama3")
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "llama3"
    assert provider.provider == "ollama"


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("openai", "gpt-4o")


def test_get_provider_error_lists_supported():
    with pytest.raises(ValueError, match="gemini"):
        get_provider("badprovider", "some-model")


def test_get_provider_satisfies_protocol():
    """Factory result must satisfy BaseLLMProvider (has generate method)."""
    provider = get_provider("ollama", "mistral")
    assert hasattr(provider, "generate")
    assert callable(provider.generate)
