"""Application settings loaded from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required environment variable {key!r} is not set")
    return value


class Settings:
    """Central settings object — reads from environment at access time."""

    @property
    def database_url(self) -> str:
        url = _require_env("DATABASE_URL")
        # Render provides postgresql:// or postgres:// — rewrite to asyncpg driver
        return url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
            "postgres://", "postgresql+asyncpg://", 1
        )

    @property
    def gemini_api_key(self) -> str:
        return _require_env("GEMINI_API_KEY")

    @property
    def dataset_root(self) -> str:
        return os.environ.get("DATASET_ROOT", "data")


settings = Settings()
