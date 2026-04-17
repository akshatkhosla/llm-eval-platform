.PHONY: dev test lint migrate

dev:
	.venv/bin/uvicorn src.evalplatform.api.app:app --reload --port 8000

test: 
	pytest tests/ -v

lint:
	ruff check src/ && ruff format --check src/

migrate:
	alembic upgrade head
