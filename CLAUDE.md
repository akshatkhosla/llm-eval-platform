# LLM Eval Platform

## Project Structure

```
src/evalplatform/
  api/          # FastAPI routes and app entry point
  core/         # Domain logic, settings, base classes
  db/           # SQLAlchemy models, sessions, repos/
  workers/      # BackgroundTask workers
  tracing/      # OpenTelemetry instrumentation
tests/          # Mirrors src/evalplatform/ layout
```

## Make Commands

| Command       | Description                          |
|---------------|--------------------------------------|
| `make dev`    | Run dev server on port 8000          |
| `make test`   | Run pytest with verbose output       |
| `make lint`   | ruff check + format check            |
| `make migrate`| Apply Alembic migrations             |

## Conventions

### Python
- Python 3.12; strict type hints everywhere; no `Any` types
- Pydantic v2 for all request/response models
- SQLAlchemy 2.0 async style: `select()`, never `session.query()`
- Repository pattern: all DB access in `src/evalplatform/db/repos/`

### LLM Providers
- All LLM calls go through `BaseLLMProvider` (provider-agnostic)
- No vendor-specific code outside of provider implementations

### Async / Background Work
- No Celery, no Redis; use FastAPI `BackgroundTasks` for async work
- Async all the way: `async def` for routes and DB calls

### Tooling
- `ruff` for linting and formatting (config in `pyproject.toml`)
- Run `make lint` before committing

### Git
- Commit messages: imperative mood, under 72 chars
- Example: `Add health endpoint`, `Fix async session leak`

## Environment

Copy `.env.example` to `.env` and fill in secrets.
Start PostgreSQL: `docker compose up -d`
