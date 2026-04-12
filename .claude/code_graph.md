# Code Graph

## src/evalplatform/api/app.py
  imports: routes.evals
  exports: app (FastAPI)
  key symbols: app (FastAPI instance with /health route and evals_router)

## src/evalplatform/api/routes/evals.py
  imports: background.run_eval_background, core.config_loader, db.repos, db.session, tracing.trace_models.EvalTrace
  exports: router (APIRouter prefix=/api/v1/evals)
  key symbols:
    - CreateRunResponse, EvalRunSummary, EvalRunDetail, EvalResultItem, EvalResultsResponse, RerunResponse (Pydantic models)
    - JudgeScorePair, SampleComparison, JudgeSummary, CompareResponse (Pydantic models for comparison)
    - create_eval() POST /api/v1/evals — accepts text/yaml or JSON{config_yaml}; 202
    - list_evals() GET /api/v1/evals — ?status=, ?limit=, ?offset=
    - compare_evals() GET /api/v1/evals/compare — ?run_ids=uuid1,uuid2, ?flagged_limit=10 (default)
      * Returns per-evaluator scores, deltas, and top N flagged samples by |avg_delta|
    - get_eval() GET /api/v1/evals/{run_id}
    - get_eval_results() GET /api/v1/evals/{run_id}/results — ?sort_by=score|sample_index, ?order=asc|desc
    - get_eval_traces() GET /api/v1/evals/{run_id}/traces → EvalTrace (404 if not stored yet)
    - rerun_eval() POST /api/v1/evals/{run_id}/rerun — clones config, 202

## src/evalplatform/api/background.py
  imports: core.runner.run_eval, core.schemas, db.repos, db.models, tracing.instrumentor.Tracer
  exports: run_eval_background
  key symbols:
    - run_eval_background(run_id, config, session_factory) — pending→running→completed|failed, saves all results and aggregate_scores, creates Tracer and persists trace_data via repos.save_trace

## src/evalplatform/core/config_loader.py
  imports: core.schemas
  exports: load_config, load_config_from_string
  key symbols:
    - load_config(path) — reads YAML file, returns EvalConfig
    - load_config_from_string(yaml_str) — parses YAML string, returns EvalConfig
    - _build_eval_config(raw) — internal builder

## src/evalplatform/core/schemas.py
  exports: LLMJudgeConfig, ContainsKeywordJudgeConfig, RegexMatchJudgeConfig, JudgeConfig,
           ProviderConfig, EvalConfig, JudgeResult, JudgeResultStatus, SampleResult, SampleStatus,
           AggregateScore, EvalRunResult

## src/evalplatform/core/runner.py
  imports: core.judges, core.providers.factory, core.schemas
  exports: run_eval
  key symbols:
    - run_eval(config, status_callback) -> EvalRunResult — async orchestrator
    - _build_judges(config) -> list[BaseJudge]
    - _load_dataset(path) -> list[dict]
    - _evaluate_sample(...) -> SampleResult
    - _compute_aggregates(samples) -> dict[int, AggregateScore]

## src/evalplatform/core/judges.py
  imports: core.schemas, core.providers.base
  exports: BaseJudge, LLMJudge, ContainsKeywordJudge, RegexMatchJudge
  key symbols: BaseJudge.judge(prompt, response, expected) -> JudgeResult

## src/evalplatform/core/providers/base.py
  exports: BaseLLMProvider (ABC)
  key symbols: generate(prompt, system, temperature, max_tokens) -> LLMResponse

## src/evalplatform/core/providers/factory.py
  exports: get_provider(provider_name, model_name) -> BaseLLMProvider

## src/evalplatform/core/providers/gemini.py
  exports: GeminiProvider

## src/evalplatform/core/providers/ollama.py
  exports: OllamaProvider

## src/evalplatform/core/settings.py
  exports: settings (Settings)
  key symbols: settings.database_url, settings.gemini_api_key (read from env)

## src/evalplatform/db/models.py
  exports: Base, EvalRun, EvalResult, RunStatus, ResultStatus
  key symbols:
    - EvalRun: id, name, config_yaml, status, provider, model, created_at, started_at,
               completed_at, error_message, total_samples, completed_samples,
               aggregate_scores, total_tokens, total_latency_ms, trace_data (JSONB)
    - EvalResult: id, run_id, sample_index, input_text, model_output, expected_output,
                  judge_scores, tokens_used, latency_ms, status, error_message

## src/evalplatform/db/session.py
  imports: core.settings
  exports: engine, AsyncSessionLocal, get_session
  key symbols: get_session() — FastAPI dependency yielding AsyncSession

## src/evalplatform/db/repos.py
  imports: db.models
  exports: create_run, get_run, list_runs, update_run_status, update_run_progress,
           save_result, get_results_for_run, get_results_for_runs, save_trace, get_trace
  key symbols: all async functions operating on AsyncSession
    - get_results_for_runs(session, run_ids: list[UUID]) -> dict[UUID, Sequence[EvalResult]]
      * Efficiently fetches results for multiple runs in a single query, grouped by run_id

## src/evalplatform/core/runner.py
  imports: core.judges, core.providers.factory, core.schemas
  exports: run_eval
  key symbols:
    - run_eval(config, status_callback, tracer=None) -> EvalRunResult — async orchestrator; wraps eval_run/sample_execution/llm_call/judge_execution in spans when tracer is provided
    - _build_judges(config) -> list[BaseJudge]
    - _load_dataset(path) -> list[dict]
    - _evaluate_sample(..., tracer=None) -> SampleResult

## src/evalplatform/tracing/trace_models.py
  exports: TraceSpan, EvalTrace
  key symbols:
    - TraceSpan: span_id, parent_id, name, start_time, end_time, duration_ms, attributes, status, children (recursive tree)
    - EvalTrace: run_id, root_span, total_spans, total_duration_ms

## src/evalplatform/tracing/instrumentor.py
  imports: tracing.trace_models
  exports: Tracer, SpanData
  key symbols:
    - Tracer(run_id) — records spans; span() asynccontextmanager; build_trace() -> EvalTrace
    - SpanData — mutable span state during recording (dataclass)

## dashboard/ (React frontend, Vite + React 18 + TypeScript + Tailwind)
  entry: dashboard/src/main.tsx → App.tsx → Layout + routes
  build tool: Vite 5, proxy /api/* → localhost:8000

## dashboard/src/types.ts
  exports: EvalStatus, EvalRunSummary, AggregateScore, EvalRunDetail, EvalResultItem, EvalResultsResponse, TraceSpan, EvalTrace,
           JudgeScorePair, SampleComparison, JudgeSummary, CompareResponse

## dashboard/src/lib/api.ts
  exports: fetchEvals(params?), fetchEvalDetail(runId), fetchEvalResults(runId), fetchEvalTraces(runId), rerunEval(runId), fetchCompare(runIdA, runIdB, flaggedLimit?), createEval(configYaml)
  notes: fetchCompare hits GET /api/v1/evals/compare?run_ids=A,B

## dashboard/src/lib/utils.ts
  exports: cn(), relativeTime(), formatDuration(), formatTokens()

## dashboard/src/components/Layout.tsx
  imports: Sidebar, react-router-dom Outlet/useMatches
  exports: Layout — sidebar + breadcrumbs + <Outlet />; manages dark/light mode via localStorage

## dashboard/src/components/Sidebar.tsx
  exports: Sidebar — logo, nav links (Eval Runs/Compare/Trends), dark toggle

## dashboard/src/components/StatusBadge.tsx
  exports: StatusBadge — colored pill for pending/running/completed/failed

## dashboard/src/components/Skeleton.tsx
  exports: Skeleton, TableRowSkeleton — animated loading placeholders

## dashboard/src/components/NewEvalModal.tsx
  exports: NewEvalModal — YAML editor modal; POSTs to /api/v1/evals via useMutation

## dashboard/src/pages/EvalsListPage.tsx
  exports: EvalsListPage — /evals route
  key features: TanStack Table, 5s polling via useQuery, name search (client), status filter (server), skeleton/empty/error states

## dashboard/src/pages/ComparePage.tsx
  exports: ComparePage — /compare route
  imports: fetchEvals, fetchCompare, recharts BarChart
  key features:
    - Two custom RunSelect dropdowns (completed runs only, mutual exclusion)
    - useQuery(['compare', runIdA, runIdB]) enabled only when both selected
    - Grouped BarChart: judge names X-axis, Run A (blue) + Run B (green) bars per group
    - DeltaTable: judge | mean_a | mean_b | delta with colored ↑↓ arrows
    - BiggestChanges: top 3 flagged_samples sorted by |avg_delta|, shows per-judge score pairs
    - useDarkMode() hook via MutationObserver on document.documentElement

## dashboard/src/pages/TrendsPage.tsx
  exports: TrendsPage — /trends route
  imports: fetchEvals, fetchEvalDetail, fetchEvalResults, recharts LineChart, useQueries
  key features:
    - Fetches completed run list, then details (aggregate_scores) + results (latency) in parallel via useQueries
    - FilterBar: date range pickers, provider dropdown, model dropdown (derived from loaded data)
    - 3 LineCharts: avg score by evaluator | token usage (total + per-sample) | latency (p50 + p95 from per-sample results)
    - Empty state when < 2 runs; "no match" state when filters exclude all runs
    - p50/p95 computed with percentile() helper; falls back to avg latency if no per-sample data

## src/evalplatform/cli.py
  imports: httpx, typer, rich (Console, Panel, Progress, Table)
  exports: app (Typer)
  key symbols:
    - run(config, --wait) — POST /api/v1/evals with YAML; optionally polls with Rich progress bar
    - status(run_id) — GET /api/v1/evals/{run_id}; prints Rich Panel with details
    - results(run_id, --format json|table) — GET /api/v1/evals/{run_id}/results; Rich table or JSON
    - compare(run_id_1, run_id_2) — GET /api/v1/evals/compare; side-by-side Rich table with deltas
    - list_runs(--status, --limit) — GET /api/v1/evals; Rich table of recent runs
    - _base_url() — reads EVALPLATFORM_API_URL env var, defaults to http://localhost:8000
    - _client() — returns httpx.Client configured with base URL
    - _api_get(path, **params) — GET helper; exits with error on 4xx/5xx

## tests/evalplatform/test_cli.py
  imports: evalplatform.cli.app, typer.testing.CliRunner
  key symbols: 15 tests covering all CLI commands using mock patches on _api_get / _client

## tests/conftest.py
  key symbols: sets DATABASE_URL and GEMINI_API_KEY env vars for test collection

## tests/evalplatform/api/test_evals.py
  imports: api.app, db.models, db.session.get_session
  key symbols:
    - _make_run / _make_result — fixture builders
    - _override_get_session — dependency override yielding AsyncMock session
    - _clear_dependency_overrides — autouse fixture to clean overrides
    - 19 integration tests covering all endpoints via httpx.AsyncClient + ASGITransport
      * 5 tests for compare_evals: success, run_not_found, invalid_format, invalid_uuid, mismatched_samples
