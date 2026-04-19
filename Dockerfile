# Stage 1: builder — install all dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools needed for some packages
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy only the files needed to resolve dependencies
COPY pyproject.toml .
COPY src/ src/

# Install into an isolated prefix so we can copy just the installed packages
RUN pip install --upgrade pip && \
    pip install --prefix=/install .


# Stage 2: runtime — lean image with only what's needed to run
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/
COPY examples/dataset.jsonl data/dataset.jsonl

EXPOSE 8000

CMD alembic upgrade head && uvicorn src.evalplatform.api.app:app --host 0.0.0.0 --port ${PORT:-8000}
