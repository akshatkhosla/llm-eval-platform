export type EvalStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface EvalRunSummary {
  run_id: string
  name: string
  status: EvalStatus
  provider: string
  model: string
  created_at: string
  started_at: string | null
  completed_at: string | null
  total_samples: number | null
  completed_samples: number
  total_tokens: number
  total_latency_ms: number
}

export interface AggregateScore {
  mean: number
  min_score: number
  max_score: number
  count: number
}

export interface EvalRunDetail extends EvalRunSummary {
  error_message: string | null
  aggregate_scores: Record<string, AggregateScore> | null
  config_yaml: string | null
}

export interface JudgeScoreEntry {
  score: number | null
  reasoning: string
  status: string
  judge_type: string
  error: string | null
}

export interface EvalResultItem {
  id: string
  sample_index: number
  input_text: string
  model_output: string | null
  expected_output: string | null
  judge_scores: Record<string, JudgeScoreEntry>
  tokens_used: number
  latency_ms: number
  status: string
  error_message: string | null
}

export interface EvalResultsResponse {
  run_id: string
  results: EvalResultItem[]
}

export interface TraceSpan {
  span_id: string
  parent_id: string | null
  name: string
  start_time: string
  end_time: string | null
  duration_ms: number | null
  attributes: Record<string, unknown>
  status: string
  children: TraceSpan[]
}

export interface EvalTrace {
  run_id: string
  root_span: TraceSpan
  total_spans: number
  total_duration_ms: number
}

// ── Compare ──────────────────────────────────────────────────────────────────

export interface JudgeScorePair {
  score_a: number | null
  score_b: number | null
  delta: number | null
}

export interface SampleComparison {
  sample_index: number
  input_text: string
  judges: Record<string, JudgeScorePair>
  avg_score_a: number | null
  avg_score_b: number | null
  avg_delta: number | null
  flagged: boolean
}

export interface JudgeSummary {
  judge_key: string
  mean_a: number | null
  mean_b: number | null
  delta: number | null
}

export interface CompareResponse {
  run_id_a: string
  run_id_b: string
  run_a: EvalRunSummary
  run_b: EvalRunSummary
  judge_summaries: JudgeSummary[]
  samples: SampleComparison[]
  flagged_samples: SampleComparison[]
}
