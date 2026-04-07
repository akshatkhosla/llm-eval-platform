# Eval System Specification

## Overview

The eval system lets users run structured LLM evaluations defined in YAML.
A run takes a dataset of prompts, sends each to a target model, and scores
every response using one or more judges (LLM-based or deterministic).
Results are stored per-row in the database with run-level aggregates.

---

## 1. Eval Config (YAML)

Users define a run in a single YAML file:

```yaml
eval:
  model: gemini/gemini-1.5-flash       # provider/model-name
  dataset: data/prompts.jsonl
  timeout_seconds: 30                  # per-call timeout (model + judge)

  judges:
    - type: llm
      model: gemini/gemini-1.5-pro     # can differ from eval model
      rubric: "Is the response accurate and complete?"

    - type: llm
      model: ollama/llama3
      rubric: "Is the tone professional?"

    - type: contains_keyword
      keyword: "python"

    - type: regex_match
      pattern: "^[A-Z]"               # response must start with capital

providers:
  gemini:
    max_concurrency: 5                 # semaphore cap (free tier ~5-15 RPM)
  ollama:
    base_url: http://localhost:11434
    max_concurrency: 20
```

### Field rules
- `eval.model` — required. Format: `<provider>/<model-name>`
- `eval.dataset` — required. Path to a JSONL file (relative to config file)
- `eval.timeout_seconds` — optional, default `30`. Applied to every individual
  HTTP call (model generation + each judge call)
- `eval.judges` — required, at least one
- `providers` — optional block; defaults apply if omitted

---

## 2. Dataset Format

JSONL, one JSON object per line:

```jsonl
{"prompt": "What is 2+2?", "expected": "4"}
{"prompt": "Name a Python web framework.", "expected": "fastapi"}
{"prompt": "Write a haiku about recursion."}
```

- `prompt` — required
- `expected` — optional; passed to judges that need a reference answer
- Additional metadata fields are allowed and stored as-is on the result row

---

## 3. Provider Abstraction

### `BaseLLMProvider` (abstract)

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, system: str | None = None) -> str:
        ...
```

### Implementations

| Provider |   Implementation | Transport |
|----------|------------------|-----------|
| `gemini` | `GeminiProvider` | `google-genai` SDK |
| `ollama` | `OllamaProvider` | `httpx` → `/v1/chat/completions` |

Provider selection is driven by the `<provider>/` prefix in the model string.
No vendor-specific code outside of `src/evalplatform/core/providers/`.

### Concurrency control

Each provider holds an `asyncio.Semaphore` sized to `max_concurrency`.
Every `complete()` call acquires the semaphore before making the HTTP request.
This caps simultaneous in-flight requests per provider regardless of dataset size.

```
semaphores: dict[str, asyncio.Semaphore] = {
    "gemini": Semaphore(5),
    "ollama": Semaphore(20),
}
```

---

## 4. Judges

### 4a. LLM Judge

**Prompt template** (system + user):

```
system:
  You are an impartial evaluator. Given a prompt, expected answer, and
  model response, score the response 0–10 based on the rubric.
  Return ONLY valid JSON: {"score": <int 0-10>, "reasoning": "<string>"}

user:
  Rubric: {rubric}
  Prompt: {prompt}
  Expected: {expected}   # omitted if not present in dataset row
  Response: {response}
```

**Parsing**: Extract JSON from response text. If JSON parse fails, retry the
judge call once. If the second attempt also fails to produce valid JSON,
mark the result for that judge as `status=error`.

**Output**:
```json
{"score": 7, "reasoning": "Correct but lacked detail."}
```

### 4b. Deterministic Judges

| type | config fields | logic |
|------|--------------|-------|
| `contains_keyword` | `keyword: str`, `case_sensitive: bool = false` | `keyword in response` → score 10 or 0 |
| `regex_match` | `pattern: str` | `re.search(pattern, response)` → score 10 or 0 |

Deterministic judges always produce `score ∈ {0, 10}` and a short `reasoning` string.
They never fail (no network calls).

### 4c. Multi-judge scoring

Each judge produces an **independent** score and reasoning. There is no
weighted aggregation — all judge results are stored individually.
Run-level aggregates are computed per judge type and across all judges.

---

## 5. Failure & Timeout Handling

| Failure type | Behavior |
|---|---|
| Model call network error | Row `status=error`, `error` field set, continue |
| Model call timeout | Same as network error |
| Judge call network error | Judge result `status=error`, other judges still run |
| Judge JSON parse failure | Retry once; if still invalid, judge result `status=error` |
| Judge call timeout | Judge result `status=error`, continue |
| Dataset row missing `prompt` | Skip row, log warning |

A row's overall `status` is:
- `passed` — all judges produced a score (no errors); scores stored
- `error` — model call failed (no judges ran)
- `partial` — model call succeeded but ≥1 judge errored

---

## 6. Resumable Runs

Runs track completed row IDs so they can be restarted after interruption.

- On start, load the run's `EvalRun` record. If `status=in_progress` and
  `completed_row_ids` is non-empty, skip those rows.
- A row is marked complete after all its judges finish (pass or error).
- Row results are written to the DB incrementally (not batched at the end).
- If the process is killed mid-row, that row is re-evaluated on restart
  (idempotent: upsert by `run_id + row_index`).

---

## 7. Database Schema

### `eval_runs`

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `config_snapshot` | JSONB | full parsed config at time of run |
| `dataset_path` | TEXT | |
| `status` | TEXT | `pending`, `in_progress`, `completed`, `failed` |
| `total_rows` | INT | |
| `completed_rows` | INT | |
| `error_rows` | INT | |
| `aggregate_scores` | JSONB | `{judge_index: {mean, min, max, pass_rate}}` |
| `created_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | nullable |

### `eval_results`

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `run_id` | UUID FK → eval_runs | |
| `row_index` | INT | position in dataset file |
| `prompt` | TEXT | |
| `expected` | TEXT | nullable |
| `response` | TEXT | nullable (null if model call failed) |
| `status` | TEXT | `passed`, `error`, `partial` |
| `error` | TEXT | nullable |
| `judge_results` | JSONB | `[{type, score, reasoning, status, error}]` |
| `metadata` | JSONB | extra fields from dataset row |
| `created_at` | TIMESTAMPTZ | |

Unique constraint on `(run_id, row_index)` to support upsert on resume.

---

## 8. Runner Execution Flow

```
load_config(yaml_path)
  → validate config (Pydantic model)
  → create EvalRun record in DB (status=pending)

load_dataset(path)
  → stream JSONL rows (don't load all into memory)
  → filter out already-completed row_indexes (resumable)

for each row (async, bounded by semaphore):
  1. call model → response (or error)
  2. if model succeeded:
       for each judge (async, bounded by semaphore):
         call judge → {score, reasoning} (or error)
  3. upsert EvalResult to DB
  4. increment EvalRun.completed_rows

on completion:
  → compute aggregate_scores
  → update EvalRun status=completed / failed
```

Concurrency: `asyncio.gather` with tasks pre-filtered through per-provider
semaphores. The dataset is streamed row-by-row using `aiofiles` to avoid
loading large files into memory.

---

## 9. File Layout

```
src/evalplatform/
  core/
    config.py          # Pydantic models for YAML config (EvalConfig, JudgeConfig, ...)
    providers/
      __init__.py
      base.py          # BaseLLMProvider ABC
      gemini.py        # GeminiProvider
      ollama.py        # OllamaProvider
      registry.py      # provider_from_string("gemini/gemini-1.5-flash") → provider instance
    judges/
      __init__.py
      base.py          # BaseJudge ABC → JudgeResult
      llm_judge.py     # LLMJudge
      deterministic.py # ContainsKeywordJudge, RegexMatchJudge
      registry.py      # judge_from_config(JudgeConfig) → judge instance
  db/
    models.py          # EvalRun, EvalResult SQLAlchemy models
    repos/
      eval_run_repo.py
      eval_result_repo.py
  workers/
    eval_runner.py     # orchestrates the full run loop
  api/
    app.py             # existing health endpoint
    routes/
      evals.py         # POST /evals (create + start run), GET /evals/{id}
```

---

## 10. API Endpoints

### `POST /evals`
Start a new eval run. Body: multipart or JSON with config YAML path.

**Request**:
```json
{"config_path": "configs/my_eval.yaml"}
```

**Response** `202 Accepted`:
```json
{"run_id": "uuid", "status": "pending"}
```

The run is handed off to a FastAPI `BackgroundTask`.

### `GET /evals/{run_id}`
Poll run status and results.

**Response**:
```json
{
  "run_id": "uuid",
  "status": "in_progress",
  "total_rows": 500,
  "completed_rows": 120,
  "error_rows": 3,
  "aggregate_scores": null
}
```

---

## 11. Open Questions / Future Work

- Auth / API keys for providers stored in `.env` or per-run config?
  (Current assumption: `.env` only, never in YAML)
- Streaming progress via SSE or WebSocket for large runs?
- CLI entrypoint (`typer`) to trigger runs without the HTTP API?
- Support for few-shot examples in judge prompts?
