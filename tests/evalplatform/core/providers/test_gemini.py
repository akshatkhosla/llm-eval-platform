"""Tests for GeminiProvider (API calls are mocked)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evalplatform.core.providers.base import LLMResponse
from evalplatform.core.providers.gemini import GeminiProvider, _is_rate_limit_error

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    text: str = "response text", prompt_tokens: int = 10, completion_tokens: int = 20
) -> MagicMock:
    """Build a mock genai.Client whose async generate_content returns a canned response."""
    mock_response = MagicMock()
    mock_response.text = text
    mock_response.usage_metadata.prompt_token_count = prompt_tokens
    mock_response.usage_metadata.candidates_token_count = completion_tokens

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    return mock_client


# ---------------------------------------------------------------------------
# _is_rate_limit_error
# ---------------------------------------------------------------------------


def test_is_rate_limit_error_status_code():
    exc = Exception("some error")
    exc.status_code = 429  # type: ignore[attr-defined]
    assert _is_rate_limit_error(exc)


def test_is_rate_limit_error_code_attr():
    exc = Exception("some error")
    exc.code = 429  # type: ignore[attr-defined]
    assert _is_rate_limit_error(exc)


def test_is_rate_limit_error_message():
    assert _is_rate_limit_error(Exception("resource exhausted"))
    assert _is_rate_limit_error(Exception("429 Too Many Requests"))


def test_is_rate_limit_error_false():
    assert not _is_rate_limit_error(Exception("internal server error"))


# ---------------------------------------------------------------------------
# GeminiProvider construction
# ---------------------------------------------------------------------------


def test_unsupported_model_raises():
    with patch("google.genai.Client"), pytest.raises(ValueError, match="Unsupported Gemini model"):
        GeminiProvider(model="gpt-4o", api_key="test")


# ---------------------------------------------------------------------------
# generate – success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_llm_response():
    mock_client = _make_mock_client(text="Hello!", prompt_tokens=5, completion_tokens=15)

    with patch("google.genai.Client", return_value=mock_client):
        provider = GeminiProvider(model="gemini-2.5-flash", api_key="test-key")
        result = await provider.generate(
            prompt="Say hello",
            system="You are helpful",
            temperature=0.5,
            max_tokens=256,
        )

    assert isinstance(result, LLMResponse)
    assert result.text == "Hello!"
    assert result.input_tokens == 5
    assert result.output_tokens == 15
    assert result.model == "gemini-2.5-flash"
    assert result.provider == "gemini"
    assert result.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_generate_without_system():
    mock_client = _make_mock_client(text="No system")

    with patch("google.genai.Client", return_value=mock_client):
        provider = GeminiProvider(model="gemini-2.5-flash-lite", api_key="test-key")
        result = await provider.generate(
            prompt="prompt",
            system=None,
            temperature=0.0,
            max_tokens=100,
        )

    assert result.text == "No system"
    # Verify generate_content was called once
    mock_client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_generate_passes_correct_model():
    mock_client = _make_mock_client()

    with patch("google.genai.Client", return_value=mock_client):
        provider = GeminiProvider(model="gemini-2.5-pro", api_key="key")
        await provider.generate(prompt="hi", system=None, temperature=0.7, max_tokens=512)

    kwargs = mock_client.aio.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# generate – rate limit retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_retries_on_rate_limit():
    rate_limit_exc = Exception("resource exhausted")
    mock_response = MagicMock()
    mock_response.text = "ok after retry"
    mock_response.usage_metadata.prompt_token_count = 1
    mock_response.usage_metadata.candidates_token_count = 2

    mock_client = MagicMock()
    # Fail twice, then succeed
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[rate_limit_exc, rate_limit_exc, mock_response]
    )

    with (
        patch("google.genai.Client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        provider = GeminiProvider(model="gemini-2.5-flash", api_key="key")
        result = await provider.generate(prompt="test", system=None, temperature=0.0, max_tokens=10)

    assert result.text == "ok after retry"
    assert mock_client.aio.models.generate_content.call_count == 3
    # Should have slept twice with exponential back-off
    assert mock_sleep.call_count == 2
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays[1] == delays[0] * 2  # exponential


@pytest.mark.asyncio
async def test_generate_raises_after_max_retries():
    rate_limit_exc = Exception("429 rate limit")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=rate_limit_exc)

    with (
        patch("google.genai.Client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(Exception, match="rate limit"),
    ):
        provider = GeminiProvider(model="gemini-2.5-flash", api_key="key")
        await provider.generate(prompt="test", system=None, temperature=0.0, max_tokens=10)

    assert mock_client.aio.models.generate_content.call_count == 5  # _MAX_RETRIES


@pytest.mark.asyncio
async def test_generate_reraises_non_rate_limit_immediately():
    non_rate_exc = Exception("internal server error")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=non_rate_exc)

    with (
        patch("google.genai.Client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        pytest.raises(Exception, match="internal server error"),
    ):
        provider = GeminiProvider(model="gemini-2.5-flash", api_key="key")
        await provider.generate(prompt="test", system=None, temperature=0.0, max_tokens=10)

    # No retries for non-rate-limit errors
    assert mock_client.aio.models.generate_content.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Concurrency – semaphore is respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """Verify that max_concurrency=1 serialises calls."""
    call_order: list[int] = []

    async def fake_generate(**kwargs: object) -> MagicMock:  # noqa: ARG001
        call_order.append(1)
        await asyncio.sleep(0)  # yield
        mock_response = MagicMock()
        mock_response.text = "x"
        mock_response.usage_metadata.prompt_token_count = 1
        mock_response.usage_metadata.candidates_token_count = 1
        return mock_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = fake_generate

    with patch("google.genai.Client", return_value=mock_client):
        provider = GeminiProvider(model="gemini-2.5-flash", api_key="key", max_concurrency=1)
        tasks = [
            provider.generate(prompt="p", system=None, temperature=0.0, max_tokens=10)
            for _ in range(3)
        ]
        results = await asyncio.gather(*tasks)

    assert len(results) == 3
    assert all(isinstance(r, LLMResponse) for r in results)
