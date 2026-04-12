import { useState, useMemo, useCallback } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type SortingState,
  type ColumnDef,
  type Row,
} from '@tanstack/react-table'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ChevronDown, Download, AlertTriangle } from 'lucide-react'
import { fetchEvalResults } from '../../lib/api'
import type { EvalResultItem } from '../../types'
import { getJudgeName } from './OverviewTab'
import { cn } from '../../lib/utils'

// ── Helpers ────────────────────────────────────────────────────────────

function sampleAvgScore(item: EvalResultItem): number | null {
  const scores = Object.values(item.judge_scores)
    .map((j) => j.score)
    .filter((s): s is number => s !== null)
  return scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null
}

function trunc(s: string | null | undefined, n: number): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}

// ── Sub-components ────────────────────────────────────────────────────

function PassBadge({ status }: { status: string }) {
  const passed = status === 'success'
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border',
        passed
          ? 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-400'
          : 'bg-red-500/10 text-red-700 border-red-500/20 dark:text-red-400',
      )}
    >
      {passed ? 'Pass' : 'Fail'}
    </span>
  )
}

function ScoreChip({ score }: { score: number | null }) {
  if (score === null)
    return <span className="text-sm text-zinc-300 dark:text-zinc-600">—</span>
  const color =
    score >= 7
      ? 'text-emerald-600 dark:text-emerald-400'
      : score >= 4
        ? 'text-amber-600 dark:text-amber-400'
        : 'text-red-600 dark:text-red-400'
  return (
    <span className={cn('text-sm font-semibold tabular-nums', color)}>{score}</span>
  )
}

function ScoreBar({ score, max = 10 }: { score: number | null; max?: number }) {
  if (score === null) return null
  const pct = Math.min(100, (score / max) * 100)
  const barColor =
    score >= 7 ? 'bg-emerald-500' : score >= 4 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', barColor)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400 w-5 text-right leading-none">
        {score}
      </span>
    </div>
  )
}

// ── Expanded row ──────────────────────────────────────────────────────

function ExpandedPanel({
  item,
  judgeKeys,
  allResults,
  colSpan,
}: {
  item: EvalResultItem
  judgeKeys: string[]
  allResults: EvalResultItem[]
  colSpan: number
}) {
  return (
    <tr>
      <td
        colSpan={colSpan}
        className="bg-zinc-50 dark:bg-zinc-900/80 border-b border-zinc-200 dark:border-zinc-800"
      >
        <div className="px-6 py-5 grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Input */}
          <div>
            <p className="text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-2">
              Input
            </p>
            <pre className="text-sm text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words font-mono bg-white dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700/60 rounded-lg p-3 max-h-44 overflow-y-auto scrollbar-thin leading-relaxed">
              {item.input_text}
            </pre>
          </div>

          {/* Output */}
          <div>
            <p className="text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-2">
              Model Output
            </p>
            <pre className="text-sm text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words font-mono bg-white dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700/60 rounded-lg p-3 max-h-44 overflow-y-auto scrollbar-thin leading-relaxed">
              {item.model_output ?? '—'}
            </pre>
          </div>

          {/* Judge details */}
          {judgeKeys.length > 0 && (
            <div className="lg:col-span-2">
              <p className="text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-3">
                Judge Scores
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {judgeKeys.map((key) => {
                  const entry = item.judge_scores[key]
                  if (!entry) return null
                  return (
                    <div
                      key={key}
                      className="bg-white dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700/60 rounded-lg p-3 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          {getJudgeName(key, allResults)}
                        </span>
                        <ScoreChip score={entry.score} />
                      </div>
                      <ScoreBar score={entry.score} />
                      {entry.reasoning && (
                        <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed line-clamp-4">
                          {entry.reasoning}
                        </p>
                      )}
                      {entry.error && (
                        <p className="text-xs text-red-500 dark:text-red-400 break-words">
                          {entry.error}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </td>
    </tr>
  )
}

// ── Main component ────────────────────────────────────────────────────

export function ResultsTab({ runId }: { runId: string }) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [passFilter, setPassFilter] = useState<'all' | 'pass' | 'fail'>('all')
  const [minScore, setMinScore] = useState(0)
  const [maxScore, setMaxScore] = useState(10)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['eval-results', runId],
    queryFn: () => fetchEvalResults(runId),
  })

  const results = data?.results ?? []

  // Collect all judge keys in sorted order
  const judgeKeys = useMemo(() => {
    const seen = new Set<string>()
    for (const r of results) {
      for (const k of Object.keys(r.judge_scores)) seen.add(k)
    }
    return Array.from(seen).sort((a, b) => Number(a) - Number(b))
  }, [results])

  // Client-side filtering
  const filtered = useMemo(() => {
    return results.filter((r) => {
      if (passFilter === 'pass' && r.status !== 'success') return false
      if (passFilter === 'fail' && r.status !== 'error') return false
      const avg = sampleAvgScore(r)
      if (avg !== null && (avg < minScore || avg > maxScore)) return false
      return true
    })
  }, [results, passFilter, minScore, maxScore])

  // Dynamic columns
  const columns = useMemo<ColumnDef<EvalResultItem>[]>(() => {
    const judgeColumns: ColumnDef<EvalResultItem>[] = judgeKeys.map((key) => ({
      id: `judge_${key}`,
      accessorFn: (row: EvalResultItem) => row.judge_scores[key]?.score ?? null,
      header: () => getJudgeName(key, results),
      cell: ({ getValue }: { getValue: () => unknown }) => (
        <ScoreChip score={getValue() as number | null} />
      ),
      sortingFn: (rowA: Row<EvalResultItem>, rowB: Row<EvalResultItem>) => {
        const a = (rowA.original.judge_scores[key]?.score ?? -1) as number
        const b = (rowB.original.judge_scores[key]?.score ?? -1) as number
        return a - b
      },
      enableSorting: true,
    }))

    return [
      {
        id: 'sample_index',
        accessorKey: 'sample_index',
        header: '#',
        cell: ({ getValue }: { getValue: () => unknown }) => (
          <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
            {getValue() as number}
          </span>
        ),
        enableSorting: true,
      },
      {
        id: 'input_text',
        accessorKey: 'input_text',
        header: 'Input',
        cell: ({ getValue }: { getValue: () => unknown }) => (
          <span className="text-xs text-zinc-600 dark:text-zinc-400 font-mono">
            {trunc(getValue() as string, 100)}
          </span>
        ),
        enableSorting: false,
      },
      {
        id: 'model_output',
        accessorKey: 'model_output',
        header: 'Output',
        cell: ({ getValue }: { getValue: () => unknown }) => (
          <span className="text-xs text-zinc-600 dark:text-zinc-400 font-mono">
            {trunc(getValue() as string | null, 100)}
          </span>
        ),
        enableSorting: false,
      },
      ...judgeColumns,
      {
        id: 'pass_fail',
        accessorKey: 'status',
        header: 'Result',
        cell: ({ getValue }: { getValue: () => unknown }) => (
          <PassBadge status={getValue() as string} />
        ),
        enableSorting: false,
      },
    ]
  }, [judgeKeys, results])

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  // CSV export
  const handleExport = useCallback(() => {
    const headers = [
      'sample_index',
      'status',
      'avg_score',
      'input',
      'output',
      ...judgeKeys.map((k) => getJudgeName(k, results)),
    ]
    const rows = filtered.map((r) => [
      r.sample_index,
      r.status,
      sampleAvgScore(r)?.toFixed(2) ?? '',
      JSON.stringify(r.input_text),
      JSON.stringify(r.model_output ?? ''),
      ...judgeKeys.map((k) => r.judge_scores[k]?.score ?? ''),
    ])
    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `eval-${runId}-results.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [filtered, judgeKeys, results, runId])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertTriangle size={20} className="text-red-500 mb-3" />
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Failed to load results</p>
      </div>
    )
  }

  const totalCols = columns.length + 1 // +1 for the expand chevron column

  return (
    <div className="flex flex-col">
      {/* ── Toolbar ────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3 px-6 py-3.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/40">
        {/* Pass/fail toggle */}
        <div className="flex rounded-lg border border-zinc-200 dark:border-zinc-700 overflow-hidden text-xs font-medium">
          {(['all', 'pass', 'fail'] as const).map((v) => (
            <button
              key={v}
              onClick={() => setPassFilter(v)}
              className={cn(
                'px-3 py-1.5 capitalize transition-colors',
                passFilter === v
                  ? 'bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900'
                  : 'text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800',
              )}
            >
              {v}
            </button>
          ))}
        </div>

        {/* Score range */}
        <div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          <span className="font-medium">Score</span>
          <input
            type="range"
            min={0}
            max={10}
            step={0.5}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-16 accent-blue-500"
            aria-label="Minimum score"
          />
          <span className="tabular-nums w-5">{minScore}</span>
          <span className="text-zinc-300 dark:text-zinc-700">–</span>
          <input
            type="range"
            min={0}
            max={10}
            step={0.5}
            value={maxScore}
            onChange={(e) => setMaxScore(Number(e.target.value))}
            className="w-16 accent-blue-500"
            aria-label="Maximum score"
          />
          <span className="tabular-nums w-5">{maxScore}</span>
        </div>

        <div className="flex-1" />

        <span className="text-xs text-zinc-400 dark:text-zinc-500">
          {filtered.length} of {results.length}
        </span>

        <button
          onClick={handleExport}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors"
        >
          <Download size={12} />
          Export CSV
        </button>
      </div>

      {/* ── Table ──────────────────────────────────────────────── */}
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {/* Expand chevron col */}
                <th className="w-9 pl-4" />
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className={cn(
                      'px-4 py-3 text-left text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider whitespace-nowrap select-none',
                      header.column.getCanSort() &&
                        'cursor-pointer hover:text-zinc-600 dark:hover:text-zinc-300',
                    )}
                  >
                    <span className="inline-flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === 'asc' && (
                        <span className="text-blue-500">↑</span>
                      )}
                      {header.column.getIsSorted() === 'desc' && (
                        <span className="text-blue-500">↓</span>
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>

          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={totalCols}
                  className="py-20 text-center text-sm text-zinc-400 dark:text-zinc-500"
                >
                  No results match your filters
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.flatMap((row) => {
                const isExpanded = expandedId === row.id
                return [
                  <tr
                    key={row.id}
                    onClick={() => setExpandedId(isExpanded ? null : row.id)}
                    className={cn(
                      'cursor-pointer transition-colors',
                      isExpanded
                        ? 'bg-zinc-50 dark:bg-zinc-900/70'
                        : 'hover:bg-zinc-50 dark:hover:bg-zinc-900/50',
                    )}
                  >
                    <td className="pl-4 pr-0 py-3.5">
                      {isExpanded ? (
                        <ChevronDown size={13} className="text-zinc-400" />
                      ) : (
                        <ChevronRight size={13} className="text-zinc-400" />
                      )}
                    </td>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-4 py-3.5">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>,
                  ...(isExpanded
                    ? [
                        <ExpandedPanel
                          key={`${row.id}-expanded`}
                          item={row.original}
                          judgeKeys={judgeKeys}
                          allResults={results}
                          colSpan={totalCols}
                        />,
                      ]
                    : []),
                ]
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
