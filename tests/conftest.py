"""Root conftest: set required environment variables before any module is imported."""

from __future__ import annotations

import os

# Provide a dummy DATABASE_URL so that evalplatform.db.session can be imported
# without a real Postgres instance.  The actual engine is never used in unit
# tests because get_session is overridden via app.dependency_overrides.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
