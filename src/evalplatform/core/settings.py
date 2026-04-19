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
        """PostgreSQL connection string, normalised to the asyncpg driver prefix."""
        url = _require_env("DATABASE_URL")
        # Render provides postgresql:// or postgres:// — rewrite to asyncpg driver
        return url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
            "postgres://", "postgresql+asyncpg://", 1
        )

    @property
    def gemini_api_key(self) -> str:
        """Google Generative AI API key. Raises RuntimeError if not set."""
        return _require_env("GEMINI_API_KEY")

    @property
    def dataset_root(self) -> str:
        """Root directory for dataset files; path traversal is checked against this."""
        return os.environ.get("DATASET_ROOT", "data")

    @property
    def allowed_origins(self) -> list[str]:
        """CORS allowed origins. Comma-separated list or '*' for all origins."""
        raw = os.environ.get("ALLOWED_ORIGINS", "*")
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
