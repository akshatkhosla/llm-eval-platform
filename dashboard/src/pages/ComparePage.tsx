import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import {
  GitCompare,
  ArrowUp,
  ArrowDown,
  Minus,
  ChevronDown,
  AlertTriangle,
  TrendingUp,
} from 'lucide-react'
import { fetchEvals, fetchCompare } from '../lib/api'
import type { EvalRunSummary, CompareResponse, JudgeSummary, SampleComparison } from '../types'
import { cn } from '../lib/utils'

// ── Dark-mode hook ───────────────────────────────────────────────────────────

function useDarkMode(): boolean {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const obs = new MutationObserver(() =>
      setDark(document.documentElement.classList.contains('dark')),
    )
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])
  return dark
}

// ── Run selector dropdown ────────────────────────────────────────────────────

interface RunSelectProps {
  label: string
  accentClass: string
  runs: EvalRunSummary[]
  value: string | null
  onChange: (id: string) => void
  exclude?: string | null
}

function RunSelect({ label, accentClass, runs, value, onChange, exclude }: RunSelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const available = runs.filter((r) => r.run_id !== exclude)
  const selected = runs.find((r) => r.run_id === value)

  return (
    <div className="flex-1 min-w-0" ref={ref}>
      <div className={cn('text-xs font-semibold uppercase tracking-widest mb-2', accentClass)}>
        {label}
      </div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-sm text-zinc-700 dark:text-zinc-200 hover:border-zinc-300 dark:hover:border-zinc-600 transition-all outline-none focus:ring-2 focus:ring-blue-500/40 shadow-sm"
      >
        <span className="truncate text-left">
          {selected ? (
            <span className="font-medium">{selected.name}</span>
          ) : (
            <span className="text-zinc-400 dark:text-zinc-500">Select a run…</span>
          )}
        </span>
        <ChevronDown
          size={13}
          className={cn('flex-shrink-0 text-zinc-400 transition-transform duration-150', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div className="absolute z-30 mt-1.5 w-72 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-xl shadow-black/10 dark:shadow-black/50 overflow-hidden">
          {available.length === 0 ? (
            <div className="px-4 py-3 text-sm text-zinc-400 dark:text-zinc-500">
              No completed runs available
            </div>
          ) : (
            <div className="max-h-64 overflow-y-auto scrollbar-thin py-1">
              {available.map((r) => (
                <button
                  key={r.run_id}
                  onClick={() => {
                    onChange(r.run_id)
                    setOpen(false)
                  }}
                  className={cn(
                    'w-full text-left px-3.5 py-2.5 text-sm transition-colors',
                    r.run_id === value
                      ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium'
                      : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/60 hover:text-zinc-900 dark:hover:text-zinc-100',
                  )}
                >
                  <div className="font-medium truncate">{r.name}</div>
                  <div className="text-xs text-zinc-400 dark:text-zinc-500 mt-0.5 font-mono">
                    {r.provider} · {r.model}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Delta indicator ──────────────────────────────────────────────────────────

function DeltaCell({ delta }: { delta: number | null }) {
  if (delta === null)
    return <span className="text-zinc-300 dark:text-zinc-600 text-sm">—</span>

  const abs = Math.abs(delta)
  if (abs < 0.005) {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-zinc-400 dark:text-zinc-500">
        <Minus size={12} /> 0.00
      </span>
    )
  }

  const improved = delta > 0
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-sm font-semibold tabular-nums',
        improved
          ? 'text-emerald-600 dark:text-emerald-400'
          : 'text-red-500 dark:text-red-400',
      )}
    >
      {improved ? <ArrowUp size={13} /> : <ArrowDown size={13} />}
      {abs.toFixed(2)}
    </span>
  )
}

function ScoreNum({ val }: { val: number | null }) {
  if (val === null)
    return <span className="text-zinc-300 dark:text-zinc-600 text-sm tabular-nums">—</span>
  const color =
    val >= 7
      ? 'text-emerald-600 dark:text-emerald-400'
      : val >= 4
        ? 'text-amber-500 dark:text-amber-400'
        : 'text-red-500 dark:text-red-400'
  return <span className={cn('text-sm font-medium tabular-nums', color)}>{val.toFixed(2)}</span>
}

// ── Grouped bar chart ────────────────────────────────────────────────────────

interface ChartData {
  judge: string
  'Run A': number
  'Run B': number
}

const CHART_COLORS = {
  runA: '#3b82f6', // blue-500
  runB: '#10b981', // emerald-500
}

interface CompareChartProps {
  summaries: JudgeSummary[]
  runAName: string
  runBName: string
  dark: boolean
}

function CompareChart({ summaries, runAName, runBName, dark }: CompareChartProps) {
  const data: ChartData[] = summaries.map((s) => ({
    judge: s.judge_key,
    'Run A': s.mean_a ?? 0,
    'Run B': s.mean_b ?? 0,
  }))

  const axisColor = dark ? '#71717a' : '#a1a1aa'
  const gridColor = dark ? '#27272a' : '#e4e4e7'
  const tooltipBg = dark ? '#18181b' : '#ffffff'
  const tooltipBorder = dark ? '#3f3f46' : '#e4e4e7'

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 4, right: 16, left: -8, bottom: 0 }} barCategoryGap="28%">
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
        <XAxis
          dataKey="judge"
          tick={{ fill: axisColor, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          domain={[0, 10]}
          tick={{ fill: axisColor, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          cursor={{ fill: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }}
          contentStyle={{
            background: tooltipBg,
            border: `1px solid ${tooltipBorder}`,
            borderRadius: 10,
            fontSize: 12,
            color: dark ? '#f4f4f5' : '#18181b',
            boxShadow: dark ? '0 8px 32px rgba(0,0,0,0.5)' : '0 4px 16px rgba(0,0,0,0.1)',
          }}
          formatter={(value: number, name: string) => [
            value.toFixed(2),
            name === 'Run A' ? runAName : runBName,
          ]}
        />
        <Legend
          formatter={(value) => (value === 'Run A' ? runAName : runBName)}
          wrapperStyle={{ fontSize: 12, color: axisColor, paddingTop: 12 }}
        />
        <Bar dataKey="Run A" fill={CHART_COLORS.runA} radius={[4, 4, 0, 0]} maxBarSize={36}>
          {data.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS.runA} />
          ))}
        </Bar>
        <Bar dataKey="Run B" fill={CHART_COLORS.runB} radius={[4, 4, 0, 0]} maxBarSize={36}>
          {data.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS.runB} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── Delta table ───────────────────────────────────────────────────────────────

function DeltaTable({
  summaries,
  runAName,
  runBName,
}: {
  summaries: JudgeSummary[]
  runAName: string
  runBName: string
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-zinc-100 dark:border-zinc-800">
            <th className="px-4 py-2.5 text-left text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">
              Evaluator
            </th>
            <th className="px-4 py-2.5 text-right text-xs font-semibold text-blue-500 uppercase tracking-wider">
              {runAName}
            </th>
            <th className="px-4 py-2.5 text-right text-xs font-semibold text-emerald-500 uppercase tracking-wider">
              {runBName}
            </th>
            <th className="px-4 py-2.5 text-right text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">
              Delta
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-50 dark:divide-zinc-800/50">
          {summaries.map((s) => (
            <tr
              key={s.judge_key}
              className="hover:bg-zinc-50/60 dark:hover:bg-zinc-900/40 transition-colors"
            >
              <td className="px-4 py-3 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                {s.judge_key}
              </td>
              <td className="px-4 py-3 text-right">
                <ScoreNum val={s.mean_a} />
              </td>
              <td className="px-4 py-3 text-right">
                <ScoreNum val={s.mean_b} />
              </td>
              <td className="px-4 py-3 text-right">
                <DeltaCell delta={s.delta} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Biggest changes section ──────────────────────────────────────────────────

function BiggestChanges({
  samples,
  runAName,
  runBName,
}: {
  samples: SampleComparison[]
  runAName: string
  runBName: string
}) {
  if (samples.length === 0) return null

  const top3 = [...samples]
    .sort((a, b) => Math.abs(b.avg_delta ?? 0) - Math.abs(a.avg_delta ?? 0))
    .slice(0, 3)

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <div className="h-6 w-6 rounded-lg bg-amber-100 dark:bg-amber-500/15 flex items-center justify-center">
          <TrendingUp size={13} className="text-amber-600 dark:text-amber-400" />
        </div>
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Biggest Changes</h2>
        <span className="text-xs text-zinc-400 dark:text-zinc-500">
          · samples with the largest score swing
        </span>
      </div>

      <div className="grid gap-3">
        {top3.map((s) => {
          const improved = (s.avg_delta ?? 0) > 0
          const borderColor = improved
            ? 'border-l-emerald-400 dark:border-l-emerald-500'
            : 'border-l-red-400 dark:border-l-red-500'
          return (
            <div
              key={s.sample_index}
              className={cn(
                'rounded-xl border border-zinc-100 dark:border-zinc-800 border-l-2 bg-white dark:bg-zinc-900/60 p-4',
                borderColor,
              )}
            >
              <div className="flex items-start justify-between gap-4 mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-zinc-400 dark:text-zinc-500">
                    #{s.sample_index}
                  </span>
                  {s.flagged && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 text-xs font-medium">
                      <AlertTriangle size={10} />
                      flagged
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <div className="text-right">
                    <div className="text-xs text-blue-500 font-semibold">
                      {runAName}
                    </div>
                    <ScoreNum val={s.avg_score_a} />
                  </div>
                  <div className="text-xs text-zinc-300 dark:text-zinc-600">→</div>
                  <div className="text-right">
                    <div className="text-xs text-emerald-500 font-semibold">
                      {runBName}
                    </div>
                    <ScoreNum val={s.avg_score_b} />
                  </div>
                  <DeltaCell delta={s.avg_delta} />
                </div>
              </div>

              <p className="text-sm text-zinc-600 dark:text-zinc-400 line-clamp-2 leading-relaxed">
                {s.input_text}
              </p>

              {Object.keys(s.judges).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {Object.entries(s.judges).map(([judge, pair]) => (
                    <span
                      key={judge}
                      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-xs text-zinc-500 dark:text-zinc-400"
                    >
                      <span className="font-medium text-zinc-700 dark:text-zinc-300">{judge}</span>
                      <span className="text-zinc-300 dark:text-zinc-600">|</span>
                      <span className="text-blue-500 tabular-nums">
                        {pair.score_a?.toFixed(1) ?? '—'}
                      </span>
                      <span className="text-zinc-300 dark:text-zinc-600">→</span>
                      <span className="text-emerald-500 tabular-nums">
                        {pair.score_b?.toFixed(1) ?? '—'}
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ── Chart / table skeleton ────────────────────────────────────────────────────

function ResultSkeleton() {
  return (
    <div className="animate-pulse space-y-6">
      <div className="rounded-2xl border border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 p-6">
        <div className="h-4 w-40 bg-zinc-100 dark:bg-zinc-800 rounded mb-5" />
        <div className="h-60 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl" />
      </div>
      <div className="rounded-2xl border border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 p-6">
        <div className="h-4 w-28 bg-zinc-100 dark:bg-zinc-800 rounded mb-5" />
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-10 bg-zinc-50 dark:bg-zinc-800/40 rounded mb-2" />
        ))}
      </div>
    </div>
  )
}

// ── Results panel ─────────────────────────────────────────────────────────────

function CompareResults({
  data,
  dark,
}: {
  data: CompareResponse
  dark: boolean
}) {
  const runAName = data.run_a.name
  const runBName = data.run_b.name

  return (
    <div className="space-y-6">
      {/* Score comparison chart */}
      {data.judge_summaries.length > 0 && (
        <section className="rounded-2xl border border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 overflow-hidden">
          <div className="px-5 py-4 border-b border-zinc-100 dark:border-zinc-800">
            <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
              Score Comparison
            </h2>
            <p className="text-xs text-zinc-400 dark:text-zinc-500 mt-0.5">
              Mean evaluator score per judge
            </p>
          </div>
          <div className="px-4 py-5">
            <CompareChart
              summaries={data.judge_summaries}
              runAName={runAName}
              runBName={runBName}
              dark={dark}
            />
          </div>
        </section>
      )}

      {/* Delta table */}
      {data.judge_summaries.length > 0 && (
        <section className="rounded-2xl border border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 overflow-hidden">
          <div className="px-5 py-4 border-b border-zinc-100 dark:border-zinc-800">
            <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
              Judge Breakdown
            </h2>
            <p className="text-xs text-zinc-400 dark:text-zinc-500 mt-0.5">
              Per-evaluator mean scores and delta (B − A)
            </p>
          </div>
          <DeltaTable
            summaries={data.judge_summaries}
            runAName={runAName}
            runBName={runBName}
          />
        </section>
      )}

      {/* Biggest changes */}
      {data.flagged_samples.length > 0 && (
        <section className="rounded-2xl border border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 p-5">
          <BiggestChanges
            samples={data.flagged_samples}
            runAName={runAName}
            runBName={runBName}
          />
        </section>
      )}

      {data.judge_summaries.length === 0 && data.flagged_samples.length === 0 && (
        <div className="rounded-2xl border border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 p-12 text-center">
          <p className="text-sm text-zinc-400 dark:text-zinc-500">
            No common evaluators found between these two runs.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function ComparePage() {
  const dark = useDarkMode()
  const [runIdA, setRunIdA] = useState<string | null>(null)
  const [runIdB, setRunIdB] = useState<string | null>(null)

  const { data: allRuns, isLoading: runsLoading } = useQuery({
    queryKey: ['evals', 'completed'],
    queryFn: () => fetchEvals({ status: 'completed', limit: 100 }),
  })

  const completedRuns: EvalRunSummary[] = allRuns ?? []

  const {
    data: compareData,
    isLoading: compareLoading,
    isError: compareError,
    error: compareErrorObj,
  } = useQuery({
    queryKey: ['compare', runIdA, runIdB],
    queryFn: () => fetchCompare(runIdA!, runIdB!),
    enabled: !!runIdA && !!runIdB,
  })

  return (
    <div className="flex flex-col min-h-full">
      {/* Page header */}
      <div className="px-6 py-5 border-b border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-xl bg-blue-50 dark:bg-blue-500/10 flex items-center justify-center">
            <GitCompare size={16} className="text-blue-600 dark:text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
              Compare Runs
            </h1>
            <p className="text-sm text-zinc-400 dark:text-zinc-500 mt-0.5">
              Side-by-side evaluation analysis
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 px-6 py-6 space-y-6 max-w-5xl w-full mx-auto">
        {/* Run selector card */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/40 p-5">
          {runsLoading ? (
            <div className="animate-pulse flex gap-6">
              <div className="flex-1 h-10 bg-zinc-100 dark:bg-zinc-800 rounded-xl" />
              <div className="flex-1 h-10 bg-zinc-100 dark:bg-zinc-800 rounded-xl" />
            </div>
          ) : completedRuns.length < 2 ? (
            <div className="flex items-center gap-2.5 text-sm text-zinc-500 dark:text-zinc-400">
              <AlertTriangle size={14} className="text-amber-500 flex-shrink-0" />
              You need at least 2 completed runs to compare. Run more evaluations first.
            </div>
          ) : (
            <div className="flex items-end gap-4 relative">
              <RunSelect
                label="Run A"
                accentClass="text-blue-500"
                runs={completedRuns}
                value={runIdA}
                onChange={setRunIdA}
                exclude={runIdB}
              />

              <div className="flex-shrink-0 pb-3">
                <div className="w-8 h-8 rounded-full border-2 border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 flex items-center justify-center">
                  <GitCompare size={14} className="text-zinc-400 dark:text-zinc-500" />
                </div>
              </div>

              <RunSelect
                label="Run B"
                accentClass="text-emerald-500"
                runs={completedRuns}
                value={runIdB}
                onChange={setRunIdB}
                exclude={runIdA}
              />
            </div>
          )}
        </div>

        {/* Results */}
        {runIdA && runIdB && (
          <>
            {compareLoading && <ResultSkeleton />}

            {compareError && (
              <div className="rounded-2xl border border-red-100 dark:border-red-500/20 bg-red-50 dark:bg-red-500/5 p-5 flex items-start gap-3">
                <AlertTriangle
                  size={16}
                  className="text-red-500 dark:text-red-400 flex-shrink-0 mt-0.5"
                />
                <div>
                  <p className="text-sm font-medium text-red-700 dark:text-red-300">
                    Failed to compare runs
                  </p>
                  <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">
                    {(compareErrorObj as Error)?.message ?? 'Unknown error'}
                  </p>
                </div>
              </div>
            )}

            {compareData && !compareLoading && (
              <CompareResults data={compareData} dark={dark} />
            )}
          </>
        )}

        {/* Empty prompt */}
        {!runIdA && !runIdB && completedRuns.length >= 2 && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-14 h-14 rounded-2xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mb-4">
              <GitCompare size={22} className="text-zinc-400 dark:text-zinc-500" />
            </div>
            <p className="text-base font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">
              Select two runs to compare
            </p>
            <p className="text-sm text-zinc-400 dark:text-zinc-500 max-w-xs leading-relaxed">
              Choose Run A and Run B from the dropdowns above to see a side-by-side analysis.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
