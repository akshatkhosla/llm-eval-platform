import { useQuery } from '@tanstack/react-query'
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts'
import { fetchEvalResults } from '../../lib/api'
import type { EvalRunDetail, EvalResultItem } from '../../types'
import { cn, formatDuration, formatTokens } from '../../lib/utils'

// ── Judge name helpers ─────────────────────────────────────────────────

const JUDGE_TYPE_LABELS: Record<string, string> = {
  LLMJudge: 'LLM',
  FaithfulnessJudge: 'Faithfulness',
  RelevanceJudge: 'Relevance',
  CoherenceJudge: 'Coherence',
  ContainsKeywordJudge: 'Keyword',
  RegexMatchJudge: 'Regex',
}

export function getJudgeName(key: string, results: EvalResultItem[]): string {
  const entry = results[0]?.judge_scores[key]
  if (entry?.judge_type) {
    return JUDGE_TYPE_LABELS[entry.judge_type] ?? entry.judge_type
  }
  return `Judge ${key}`
}

// ── Score gauge (SVG semicircle arc) ──────────────────────────────────

function ScoreGauge({ score, max = 10 }: { score: number; max?: number }) {
  // Draws a top-semicircle gauge using stroke-dasharray/dashoffset.
  // sweep-flag=0 (counterclockwise in SVG screen coords = top arc).
  const pct = Math.min(1, Math.max(0, score / max))
  const r = 28
  const cx = 36
  const cy = 40
  const circumference = Math.PI * r
  const offset = circumference * (1 - pct)

  return (
    <svg width="72" height="44" viewBox="0 0 72 44" aria-hidden="true">
      {/* Track */}
      <path
        d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 0 ${cx + r} ${cy}`}
        fill="none"
        strokeWidth="5"
        strokeLinecap="round"
        className="stroke-zinc-200 dark:stroke-zinc-800"
      />
      {/* Fill */}
      {pct > 0 && (
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 0 ${cx + r} ${cy}`}
          fill="none"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="stroke-amber-500 transition-all duration-700"
        />
      )}
    </svg>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  children,
}: {
  label: string
  value?: React.ReactNode
  sub?: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4">
      <span className="text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">
        {label}
      </span>
      {children ?? (
        <span className="text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-100 mt-1 leading-none">
          {value}
        </span>
      )}
      {sub && (
        <span className="text-xs text-zinc-400 dark:text-zinc-600 mt-0.5">{sub}</span>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────

export function OverviewTab({ run }: { run: EvalRunDetail }) {
  const { data } = useQuery({
    queryKey: ['eval-results', run.run_id],
    queryFn: () => fetchEvalResults(run.run_id),
    enabled: run.status === 'completed' || run.status === 'failed',
  })

  const results = data?.results ?? []

  // Overall average score across all judges and all results
  const avgScore: number | null = (() => {
    const all: number[] = []
    for (const r of results) {
      for (const j of Object.values(r.judge_scores)) {
        if (j.score !== null) all.push(j.score)
      }
    }
    return all.length > 0 ? all.reduce((a, b) => a + b, 0) / all.length : null
  })()

  const perSampleLatency =
    run.total_samples != null && run.total_samples > 0
      ? run.total_latency_ms / run.total_samples
      : null

  // Radar chart: one point per judge index using aggregate_scores from the run
  const radarData = Object.entries(run.aggregate_scores ?? {}).map(([key, agg]) => ({
    judge: getJudgeName(key, results),
    score: Math.round(agg.mean * 10) / 10,
    fullMark: 10,
  }))

  // Pass/fail counts
  const passed = results.filter((r) => r.status === 'success').length
  const failed = results.filter((r) => r.status === 'error').length
  const pieData = [
    { name: 'Passed', value: passed, color: '#10b981' },
    { name: 'Failed', value: failed, color: '#ef4444' },
  ].filter((d) => d.value > 0)

  const scoreColor =
    avgScore === null
      ? 'text-zinc-300 dark:text-zinc-600'
      : avgScore >= 7
        ? 'text-emerald-600 dark:text-emerald-400'
        : avgScore >= 4
          ? 'text-amber-600 dark:text-amber-400'
          : 'text-red-600 dark:text-red-400'

  return (
    <div className="px-6 py-5 space-y-5">
      {/* ── Stats row ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard
          label="Total Samples"
          value={run.total_samples ?? '—'}
          sub={
            run.status === 'running' && run.total_samples != null
              ? `${run.completed_samples} done`
              : undefined
          }
        />

        <StatCard label="Avg Score">
          <div className="flex items-center gap-2 mt-1">
            {avgScore !== null ? (
              <>
                <ScoreGauge score={avgScore} />
                <span className={cn('text-2xl font-semibold tabular-nums leading-none', scoreColor)}>
                  {avgScore.toFixed(1)}
                </span>
              </>
            ) : (
              <span className="text-2xl font-semibold text-zinc-300 dark:text-zinc-600 leading-none mt-1">
                —
              </span>
            )}
          </div>
        </StatCard>

        <StatCard
          label="Total Tokens"
          value={run.total_tokens === 0 ? '—' : formatTokens(run.total_tokens)}
        />

        <StatCard label="Duration" value={formatDuration(run.total_latency_ms)} />

        <StatCard
          label="Avg Latency / Sample"
          value={perSampleLatency != null ? formatDuration(perSampleLatency) : '—'}
        />
      </div>

      {/* ── Charts row ──────────────────────────────────────────── */}
      {results.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Radar chart — needs at least 3 judges to look sensible */}
          {radarData.length >= 2 && (
            <div className="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                Score by Evaluator
              </h3>
              <p className="text-xs text-zinc-400 dark:text-zinc-600 mb-4">
                Average score per judge across all samples
              </p>
              <ResponsiveContainer width="100%" height={240}>
                <RadarChart data={radarData} margin={{ top: 10, right: 20, bottom: 10, left: 20 }}>
                  <PolarGrid stroke="#27272a" />
                  <PolarAngleAxis
                    dataKey="judge"
                    tick={{ fontSize: 11, fill: '#a1a1aa' }}
                  />
                  <PolarRadiusAxis
                    angle={30}
                    domain={[0, 10]}
                    tick={{ fontSize: 9, fill: '#52525b' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Radar
                    dataKey="score"
                    stroke="#f59e0b"
                    fill="#f59e0b"
                    fillOpacity={0.15}
                    strokeWidth={2}
                    dot={{ fill: '#f59e0b', r: 3 }}
                  />
                  <Tooltip
                    formatter={(value: number) => [value.toFixed(1), 'Score']}
                    contentStyle={{
                      background: '#18181b',
                      border: '1px solid #27272a',
                      borderRadius: '8px',
                      fontSize: '12px',
                      color: '#f4f4f5',
                    }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Pass / fail donut */}
          {pieData.length > 0 && (
            <div className="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                Pass / Fail Breakdown
              </h3>
              <p className="text-xs text-zinc-400 dark:text-zinc-600 mb-4">
                Sample-level outcome distribution
              </p>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="45%"
                    innerRadius={60}
                    outerRadius={88}
                    paddingAngle={3}
                    dataKey="value"
                    label={({ name, value }) => `${name}: ${value as number}`}
                    labelLine={false}
                  >
                    {pieData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Legend
                    iconType="circle"
                    iconSize={8}
                    formatter={(value: string) => (
                      <span style={{ fontSize: 12, color: '#a1a1aa' }}>{value}</span>
                    )}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#18181b',
                      border: '1px solid #27272a',
                      borderRadius: '8px',
                      fontSize: '12px',
                      color: '#f4f4f5',
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* ── Error message ────────────────────────────────────────── */}
      {run.status === 'failed' && run.error_message && (
        <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-xl p-4">
          <p className="text-xs font-semibold text-red-600 dark:text-red-400 uppercase tracking-wider mb-1.5">
            Error
          </p>
          <p className="text-sm text-red-700 dark:text-red-300 font-mono break-all leading-relaxed">
            {run.error_message}
          </p>
        </div>
      )}
    </div>
  )
}
