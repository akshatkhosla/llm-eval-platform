import { useState, useEffect, useMemo } from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { TrendingUp, Calendar, Filter, ChevronDown, AlertTriangle } from 'lucide-react'
import { format, parseISO, startOfDay, endOfDay } from 'date-fns'
import { fetchEvals, fetchEvalDetail, fetchEvalResults } from '../lib/api'
import type { EvalRunDetail, EvalResultsResponse } from '../types'
import { cn, formatTokens, formatDuration } from '../lib/utils'

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

// ── Percentile helper ────────────────────────────────────────────────────────

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const idx = Math.ceil((p / 100) * sorted.length) - 1
  return sorted[Math.max(0, idx)]
}

// ── Color palette for lines ──────────────────────────────────────────────────

const LINE_COLORS = [
  '#3b82f6', // blue-500
  '#10b981', // emerald-500
  '#f59e0b', // amber-500
  '#ef4444', // red-500
  '#8b5cf6', // violet-500
  '#ec4899', // pink-500
  '#06b6d4', // cyan-500
  '#84cc16', // lime-500
]

// ── Shared chart theme ────────────────────────────────────────────────────────

function chartTheme(dark: boolean) {
  return {
    axisColor: dark ? '#71717a' : '#a1a1aa',
    gridColor: dark ? '#27272a' : '#e4e4e7',
    tooltipBg: dark ? '#18181b' : '#ffffff',
    tooltipBorder: dark ? '#3f3f46' : '#e4e4e7',
    tooltipText: dark ? '#f4f4f5' : '#18181b',
  }
}

// ── Filter bar ───────────────────────────────────────────────────────────────

interface FilterBarProps {
  dateFrom: string
  dateTo: string
  onDateFrom: (v: string) => void
  onDateTo: (v: string) => void
  providers: string[]
  provider: string
  onProvider: (v: string) => void
  models: string[]
  model: string
  onModel: (v: string) => void
}

function FilterBar({
  dateFrom, dateTo, onDateFrom, onDateTo,
  providers, provider, onProvider,
  models, model, onModel,
}: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/40">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">
        <Filter size={11} />
        Filters
      </div>

      <div className="w-px h-4 bg-zinc-200 dark:bg-zinc-700" />

      {/* Date range */}
      <div className="flex items-center gap-2">
        <Calendar size={12} className="text-zinc-400 dark:text-zinc-500" />
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => onDateFrom(e.target.value)}
          className="text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-700 dark:text-zinc-300 outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all cursor-pointer"
        />
        <span className="text-xs text-zinc-400 dark:text-zinc-500">to</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => onDateTo(e.target.value)}
          className="text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-700 dark:text-zinc-300 outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all cursor-pointer"
        />
      </div>

      {/* Provider */}
      <FilterSelect label="Provider" value={provider} onChange={onProvider} options={providers} allLabel="All providers" />

      {/* Model */}
      <FilterSelect label="Model" value={model} onChange={onModel} options={models} allLabel="All models" />
    </div>
  )
}

function FilterSelect({
  label, value, onChange, options, allLabel,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: string[]
  allLabel: string
}) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const handler = () => setOpen(false)
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const display = value || allLabel

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg text-zinc-600 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-600 transition-all outline-none focus:ring-2 focus:ring-blue-500/40 whitespace-nowrap shadow-sm"
      >
        {display}
        <ChevronDown size={11} className={cn('text-zinc-400 transition-transform duration-150', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1.5 min-w-[140px] bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-lg shadow-black/10 dark:shadow-black/40 overflow-hidden z-30 py-1">
          <button
            onClick={() => { onChange(''); setOpen(false) }}
            className={cn(
              'w-full text-left px-3.5 py-2 text-sm transition-colors',
              value === ''
                ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium'
                : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/60',
            )}
          >
            {allLabel}
          </button>
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false) }}
              className={cn(
                'w-full text-left px-3.5 py-2 text-sm transition-colors',
                value === opt
                  ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium'
                  : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/60',
              )}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Chart card wrapper ────────────────────────────────────────────────────────

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 overflow-hidden">
      <div className="px-5 py-4 border-b border-zinc-100 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">{title}</h2>
        {subtitle && (
          <p className="text-xs text-zinc-400 dark:text-zinc-500 mt-0.5">{subtitle}</p>
        )}
      </div>
      <div className="px-4 py-5">{children}</div>
    </section>
  )
}

// ── Chart skeleton ────────────────────────────────────────────────────────────

function ChartSkeleton() {
  return (
    <div className="animate-pulse space-y-5">
      {[1, 2, 3].map((i) => (
        <div key={i} className="rounded-2xl border border-zinc-100 dark:border-zinc-800 p-6">
          <div className="h-4 w-40 bg-zinc-100 dark:bg-zinc-800 rounded mb-5" />
          <div className="h-52 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl" />
        </div>
      ))}
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyTrends() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-14 h-14 rounded-2xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mb-4">
        <TrendingUp size={22} className="text-zinc-400 dark:text-zinc-500" />
      </div>
      <p className="text-base font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">
        Run more evals to see trends
      </p>
      <p className="text-sm text-zinc-400 dark:text-zinc-500 max-w-xs leading-relaxed">
        Trends require at least 2 completed evaluation runs. Once you have more data, charts will
        appear here.
      </p>
    </div>
  )
}

function NoFilteredData() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <AlertTriangle size={20} className="text-amber-400 mb-3" />
      <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
        No runs match your filters
      </p>
      <p className="text-xs text-zinc-400 dark:text-zinc-500">
        Try adjusting the date range, provider, or model.
      </p>
    </div>
  )
}

// ── Main charts ───────────────────────────────────────────────────────────────

interface RunPoint {
  runId: string
  provider: string
  model: string
  dateLabel: string
  rawDate: string
  tokens: number
  tokensPerSample: number
  avgLatencyMs: number
  scores: Record<string, number>
  p50Latency: number
  p95Latency: number
}

interface ChartsProps {
  points: RunPoint[]
  dark: boolean
}

function ScoreChart({ points, dark }: ChartsProps) {
  const { axisColor, gridColor, tooltipBg, tooltipBorder, tooltipText } = chartTheme(dark)

  // Collect all judge keys
  const judgeKeys = useMemo(() => {
    const keys = new Set<string>()
    points.forEach((p) => Object.keys(p.scores).forEach((k) => keys.add(k)))
    return [...keys]
  }, [points])

  if (judgeKeys.length === 0) {
    return (
      <div className="h-52 flex items-center justify-center text-sm text-zinc-400 dark:text-zinc-500">
        No evaluator scores found in these runs.
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={points} margin={{ top: 4, right: 16, left: -8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
        <XAxis
          dataKey="dateLabel"
          tick={{ fill: axisColor, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          domain={[0, 10]}
          tick={{ fill: axisColor, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <ReferenceLine y={5} stroke={gridColor} strokeDasharray="4 4" />
        <Tooltip
          contentStyle={{
            background: tooltipBg,
            border: `1px solid ${tooltipBorder}`,
            borderRadius: 10,
            fontSize: 12,
            color: tooltipText,
            boxShadow: dark ? '0 8px 32px rgba(0,0,0,0.5)' : '0 4px 16px rgba(0,0,0,0.1)',
          }}
          formatter={(v: number, name: string) => [v.toFixed(2), name]}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: axisColor, paddingTop: 10 }} />
        {judgeKeys.map((key, i) => (
          <Line
            key={key}
            type="monotone"
            dataKey={`scores.${key}`}
            name={key}
            stroke={LINE_COLORS[i % LINE_COLORS.length]}
            strokeWidth={2}
            dot={{ r: 3, strokeWidth: 0 }}
            activeDot={{ r: 5 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function TokenChart({ points, dark }: ChartsProps) {
  const { axisColor, gridColor, tooltipBg, tooltipBorder, tooltipText } = chartTheme(dark)

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={points} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
        <XAxis
          dataKey="dateLabel"
          tick={{ fill: axisColor, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: axisColor, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => formatTokens(v)}
          width={52}
        />
        <Tooltip
          contentStyle={{
            background: tooltipBg,
            border: `1px solid ${tooltipBorder}`,
            borderRadius: 10,
            fontSize: 12,
            color: tooltipText,
            boxShadow: dark ? '0 8px 32px rgba(0,0,0,0.5)' : '0 4px 16px rgba(0,0,0,0.1)',
          }}
          formatter={(v: number) => [formatTokens(v), 'Tokens']}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: axisColor, paddingTop: 10 }} />
        <Line
          type="monotone"
          dataKey="tokens"
          name="Total tokens"
          stroke={LINE_COLORS[0]}
          strokeWidth={2}
          dot={{ r: 3, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="tokensPerSample"
          name="Tokens / sample"
          stroke={LINE_COLORS[2]}
          strokeWidth={2}
          strokeDasharray="5 3"
          dot={{ r: 3, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

function LatencyChart({ points, dark }: ChartsProps) {
  const { axisColor, gridColor, tooltipBg, tooltipBorder, tooltipText } = chartTheme(dark)

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={points} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
        <XAxis
          dataKey="dateLabel"
          tick={{ fill: axisColor, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: axisColor, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => formatDuration(v)}
          width={52}
        />
        <Tooltip
          contentStyle={{
            background: tooltipBg,
            border: `1px solid ${tooltipBorder}`,
            borderRadius: 10,
            fontSize: 12,
            color: tooltipText,
            boxShadow: dark ? '0 8px 32px rgba(0,0,0,0.5)' : '0 4px 16px rgba(0,0,0,0.1)',
          }}
          formatter={(v: number, name: string) => [formatDuration(v), name]}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: axisColor, paddingTop: 10 }} />
        <Line
          type="monotone"
          dataKey="p50Latency"
          name="p50 (median)"
          stroke={LINE_COLORS[1]}
          strokeWidth={2}
          dot={{ r: 3, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="p95Latency"
          name="p95"
          stroke={LINE_COLORS[3]}
          strokeWidth={2}
          strokeDasharray="5 3"
          dot={{ r: 3, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function TrendsPage() {
  const dark = useDarkMode()

  // Filters
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [providerFilter, setProviderFilter] = useState('')
  const [modelFilter, setModelFilter] = useState('')

  // Fetch all completed runs (summaries)
  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ['evals', 'completed', 'all'],
    queryFn: () => fetchEvals({ status: 'completed', limit: 50 }),
  })

  // Fetch details for each run (aggregate_scores)
  const detailQueries = useQueries({
    queries: (runs ?? []).map((r) => ({
      queryKey: ['eval', r.run_id],
      queryFn: () => fetchEvalDetail(r.run_id),
      enabled: !!runs,
    })),
  })

  // Fetch per-sample results for p50/p95 latency computation
  const resultsQueries = useQueries({
    queries: (runs ?? []).map((r) => ({
      queryKey: ['eval-results', r.run_id],
      queryFn: () => fetchEvalResults(r.run_id),
      enabled: !!runs,
    })),
  })

  const detailsLoaded = detailQueries.every((q) => q.isSuccess || q.isError)
  const resultsLoaded = resultsQueries.every((q) => q.isSuccess || q.isError)
  const isLoading = runsLoading || !detailsLoaded || !resultsLoaded

  const details: EvalRunDetail[] = detailQueries
    .map((q) => q.data)
    .filter(Boolean) as EvalRunDetail[]

  const resultsMap = useMemo(() => {
    const map: Record<string, EvalResultsResponse> = {}
    resultsQueries.forEach((q) => {
      if (q.data) map[q.data.run_id] = q.data
    })
    return map
  }, [resultsQueries])

  // Unique providers and models for filter dropdowns
  const providers = useMemo(
    () => [...new Set(details.map((d) => d.provider).filter(Boolean))].sort(),
    [details],
  )
  const allModels = useMemo(
    () => [...new Set(details.map((d) => d.model).filter(Boolean))].sort(),
    [details],
  )

  // Build run points from details + results
  const allPoints: RunPoint[] = useMemo(() => {
    return details
      .map((d) => {
        const samples = d.completed_samples || 1
        const completedAt = d.completed_at ?? d.created_at
        const perSampleResults = resultsMap[d.run_id]?.results ?? []
        const latencies = perSampleResults.map((r) => r.latency_ms).filter((v) => v > 0)

        const scores: Record<string, number> = {}
        if (d.aggregate_scores) {
          Object.entries(d.aggregate_scores).forEach(([key, val]) => {
            const mean = (val as { mean?: number }).mean
            if (mean !== undefined) scores[key] = mean
          })
        }

        return {
          runId: d.run_id,
          provider: d.provider,
          model: d.model,
          rawDate: completedAt,
          dateLabel: format(parseISO(completedAt), 'MMM d'),
          tokens: d.total_tokens,
          tokensPerSample: Math.round(d.total_tokens / samples),
          avgLatencyMs: d.total_latency_ms / samples,
          scores,
          p50Latency: latencies.length > 0 ? percentile(latencies, 50) : d.total_latency_ms / samples,
          p95Latency: latencies.length > 0 ? percentile(latencies, 95) : d.total_latency_ms / samples,
        } satisfies RunPoint
      })
      .sort((a, b) => new Date(a.rawDate).getTime() - new Date(b.rawDate).getTime())
  }, [details, resultsMap])

  // Apply filters
  const filteredPoints = useMemo(() => {
    return allPoints.filter((p) => {
      if (providerFilter && p.provider !== providerFilter) return false
      if (modelFilter && p.model !== modelFilter) return false
      if (dateFrom || dateTo) {
        const date = parseISO(p.rawDate)
        if (dateFrom && date < startOfDay(parseISO(dateFrom))) return false
        if (dateTo && date > endOfDay(parseISO(dateTo))) return false
      }
      return true
    })
  }, [allPoints, providerFilter, modelFilter, dateFrom, dateTo])

  const hasEnoughData = (runs?.length ?? 0) >= 2
  const hasFilteredData = filteredPoints.length >= 2

  return (
    <div className="flex flex-col min-h-full">
      {/* Page header */}
      <div className="px-6 py-5 border-b border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 flex items-center justify-center">
            <TrendingUp size={16} className="text-emerald-600 dark:text-emerald-400" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Trends</h1>
            <p className="text-sm text-zinc-400 dark:text-zinc-500 mt-0.5">
              Score, token, and latency trends across completed runs
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 px-6 py-6 space-y-6 max-w-5xl w-full mx-auto">
        {/* Filter bar — always visible if we have any runs */}
        {!runsLoading && hasEnoughData && (
          <FilterBar
            dateFrom={dateFrom}
            dateTo={dateTo}
            onDateFrom={setDateFrom}
            onDateTo={setDateTo}
            providers={providers}
            provider={providerFilter}
            onProvider={setProviderFilter}
            models={allModels}
            model={modelFilter}
            onModel={setModelFilter}
          />
        )}

        {/* Loading */}
        {isLoading && <ChartSkeleton />}

        {/* Not enough runs */}
        {!isLoading && !hasEnoughData && <EmptyTrends />}

        {/* Filters return no data */}
        {!isLoading && hasEnoughData && !hasFilteredData && <NoFilteredData />}

        {/* Charts */}
        {!isLoading && hasEnoughData && hasFilteredData && (
          <>
            <ChartCard
              title="Average Score by Evaluator"
              subtitle="Mean judge score per run, over time"
            >
              <ScoreChart points={filteredPoints} dark={dark} />
            </ChartCard>

            <ChartCard
              title="Token Usage Over Time"
              subtitle="Total tokens and tokens per sample"
            >
              <TokenChart points={filteredPoints} dark={dark} />
            </ChartCard>

            <ChartCard
              title="Latency Over Time"
              subtitle="p50 (median) and p95 per-sample latency"
            >
              <LatencyChart points={filteredPoints} dark={dark} />
            </ChartCard>
          </>
        )}
      </div>
    </div>
  )
}
