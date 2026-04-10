"""Application settings loaded from environment variables."""

from __future__ import annotations

import os


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required environment variable {key!r} is not set")
    return value


class Settings:
    """Central settings object — reads from environment at access time."""

    @property
    def database_url(self) -> str:
        return _require_env("DATABASE_URL")

    @property
    def gemini_api_key(self) -> str:
        return _require_env("GEMINI_API_KEY")


settings = Settings()
