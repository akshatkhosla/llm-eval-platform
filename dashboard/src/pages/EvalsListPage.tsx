import { useState, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, RefreshCw, ChevronDown, BarChart2, AlertTriangle, ChevronRight, Trash2, ChevronLeft } from 'lucide-react'
import { fetchEvals, deleteEval } from '../lib/api'
import type { EvalRunSummary } from '../types'
import { StatusBadge } from '../components/StatusBadge'
import { TableRowSkeleton } from '../components/Skeleton'
import { NewEvalModal } from '../components/NewEvalModal'
import { cn, relativeTime, formatDuration, formatTokens } from '../lib/utils'

// ── Sub-components ──────────────────────────────────────────────────────────

function SamplesProgress({
  completed,
  total,
  allErrored = false,
}: {
  completed: number
  total: number | null
  allErrored?: boolean
}) {
  if (total === null || total === 0)
    return <span className="text-sm text-zinc-400 dark:text-zinc-500">—</span>
  const pct = Math.min(100, (completed / total) * 100)
  const isComplete = completed >= total
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden min-w-[48px] max-w-[80px]">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            allErrored ? 'bg-red-500' : isComplete ? 'bg-emerald-500' : 'bg-blue-500',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn(
        'text-xs tabular-nums whitespace-nowrap',
        allErrored ? 'text-red-500 dark:text-red-400' : 'text-zinc-500 dark:text-zinc-400',
      )}>
        {completed}/{total}
      </span>
    </div>
  )
}

function ScoreCell({ score }: { score: number | null }) {
  if (score === null)
    return <span className="text-sm text-zinc-300 dark:text-zinc-600">—</span>

  const barColor =
    score >= 7 ? 'bg-emerald-500' : score >= 4 ? 'bg-amber-500' : 'bg-red-500'
  const textColor =
    score >= 7
      ? 'text-emerald-700 dark:text-emerald-400'
      : score >= 4
        ? 'text-amber-700 dark:text-amber-400'
        : 'text-red-700 dark:text-red-400'
  const pct = Math.min(100, (score / 10) * 100)

  return (
    <div className="flex items-center gap-2">
      <div className="w-14 h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden flex-shrink-0">
        <div className={cn('h-full rounded-full', barColor)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn('text-sm font-semibold tabular-nums', textColor)}>
        {score.toFixed(1)}
      </span>
    </div>
  )
}

function ProviderChip({ provider }: { provider: string }) {
  const styles: Record<string, string> = {
    gemini: 'bg-blue-50 text-blue-700 border-blue-100 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20',
    ollama: 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20',
  }
  const cls =
    styles[provider.toLowerCase()] ??
    'bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700'
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium capitalize border',
        cls,
      )}
    >
      {provider}
    </span>
  )
}

// ── Column definitions ───────────────────────────────────────────────────────

const col = createColumnHelper<EvalRunSummary>()

const COLUMNS = [
  col.accessor('name', {
    header: 'Name',
    cell: (info) => (
      <span className="font-medium text-zinc-900 dark:text-zinc-100 text-sm truncate max-w-[200px] block">
        {info.getValue()}
      </span>
    ),
  }),
  col.display({
    id: 'status',
    header: 'Status',
    cell: ({ row }) => {
      const { status, passed_samples, failed_samples } = row.original
      if (status === 'completed' && (passed_samples > 0 || failed_samples > 0)) {
        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            {passed_samples > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                {passed_samples} passed
              </span>
            )}
            {failed_samples > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-red-50 text-red-700 border border-red-100 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0" />
                {failed_samples} failed
              </span>
            )}
          </div>
        )
      }
      return <StatusBadge status={status} />
    },
  }),
  col.accessor('provider', {
    header: 'Provider',
    cell: (info) => <ProviderChip provider={info.getValue()} />,
  }),
  col.accessor('model', {
    header: 'Model',
    cell: (info) => (
      <span
        className="text-xs font-mono text-zinc-500 dark:text-zinc-400 truncate max-w-[160px] block"
        title={info.getValue()}
      >
        {info.getValue()}
      </span>
    ),
  }),
  col.display({
    id: 'samples',
    header: 'Samples',
    cell: ({ row }) => {
      const { completed_samples, total_samples, total_tokens, status } = row.original
      // "All errored" = run finished but no LLM call ever succeeded (tokens = 0).
      // Empty aggregate_scores alone isn't enough — it can also mean judges
      // failed while samples themselves succeeded.
      const allErrored =
        status === 'completed' && total_tokens === 0 && completed_samples > 0
      return (
        <SamplesProgress
          completed={completed_samples}
          total={total_samples}
          allErrored={allErrored}
        />
      )
    },
  }),
  col.display({
    id: 'avg_score',
    header: 'Avg Score',
    cell: ({ row }) => {
      const scores = row.original.aggregate_scores
      if (!scores) return <ScoreCell score={null} />
      const means = Object.values(scores).map((s) => s.mean)
      const avg = means.length > 0 ? means.reduce((a, b) => a + b, 0) / means.length : null
      return <ScoreCell score={avg} />
    },
  }),
  col.accessor('total_tokens', {
    header: 'Tokens',
    cell: (info) => (
      <span className="text-sm text-zinc-500 dark:text-zinc-400 tabular-nums">
        {formatTokens(info.getValue())}
      </span>
    ),
  }),
  col.display({
    id: 'duration',
    header: 'Duration',
    cell: ({ row }) => {
      const { total_latency_ms, started_at, completed_at } = row.original
      const ms = total_latency_ms > 0
        ? total_latency_ms
        : started_at && completed_at
          ? new Date(completed_at).getTime() - new Date(started_at).getTime()
          : 0
      return (
        <span className="text-sm text-zinc-500 dark:text-zinc-400 tabular-nums">
          {formatDuration(ms)}
        </span>
      )
    },
  }),
  col.accessor('created_at', {
    header: 'Created',
    cell: (info) => (
      <span
        className="text-sm text-zinc-400 dark:text-zinc-500 whitespace-nowrap"
        title={info.getValue()}
      >
        {relativeTime(info.getValue())}
      </span>
    ),
  }),
]

// ── Status filter options ────────────────────────────────────────────────────

const STATUSES: Array<{ value: string | null; label: string }> = [
  { value: null, label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

const PAGE_SIZES = [5, 10, 50, 100] as const
type PageSize = (typeof PAGE_SIZES)[number]

// ── Empty / Error states ─────────────────────────────────────────────────────

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <tr>
      <td colSpan={COLUMNS.length}>
        <div className="flex flex-col items-center justify-center py-24 px-4">
          <div className="w-14 h-14 rounded-2xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mb-5 shadow-inner">
            <BarChart2 size={24} className="text-zinc-400 dark:text-zinc-500" />
          </div>
          <p className="text-base font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">
            {hasFilters ? 'No runs match your filters' : 'No eval runs yet'}
          </p>
          <p className="text-sm text-zinc-400 dark:text-zinc-500 text-center max-w-xs leading-relaxed">
            {hasFilters
              ? 'Try adjusting your search or clearing the status filter.'
              : 'Click "New Eval Run" above to kick off your first evaluation.'}
          </p>
        </div>
      </td>
    </tr>
  )
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 px-4">
      <div className="w-14 h-14 rounded-2xl bg-red-50 dark:bg-red-500/10 flex items-center justify-center mb-5">
        <AlertTriangle size={22} className="text-red-500 dark:text-red-400" />
      </div>
      <p className="text-base font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">
        Failed to load eval runs
      </p>
      <p className="text-sm text-zinc-400 dark:text-zinc-500 text-center max-w-xs mb-6 leading-relaxed">
        Could not reach the API. Make sure the backend is running on port 8000.
      </p>
      <button
        onClick={onRetry}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors"
      >
        <RefreshCw size={14} />
        Try again
      </button>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export function EvalsListPage() {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [nameFilter, setNameFilter] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [pageSize, setPageSize] = useState<PageSize>(10)
  const [pageIndex, setPageIndex] = useState(0)
  const [pageSizeOpen, setPageSizeOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const pageSizeRef = useRef<HTMLDivElement>(null)

  // Reset to first page whenever the filter or page size changes
  useEffect(() => {
    setPageIndex(0)
  }, [statusFilter, pageSize])

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!dropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [dropdownOpen])

  useEffect(() => {
    if (!pageSizeOpen) return
    const handler = (e: MouseEvent) => {
      if (pageSizeRef.current && !pageSizeRef.current.contains(e.target as Node)) {
        setPageSizeOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [pageSizeOpen])

  const queryClient = useQueryClient()
  const deleteMutation = useMutation({
    mutationFn: deleteEval,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['evals'] }),
  })

  const columns = useMemo(
    () => [
      ...COLUMNS,
      col.display({
        id: 'action',
        header: '',
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation()
                if (window.confirm(`Delete "${row.original.name}"? This cannot be undone.`)) {
                  deleteMutation.mutate(row.original.run_id)
                }
              }}
              className="p-1 rounded opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 transition-all"
              title="Delete run"
            >
              <Trash2 size={13} />
            </button>
            <ChevronRight
              size={14}
              className="text-zinc-300 dark:text-zinc-600 opacity-0 group-hover:opacity-100 transition-opacity"
            />
          </div>
        ),
      }),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [deleteMutation.mutate],
  )

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['evals', statusFilter, pageIndex, pageSize],
    queryFn: () =>
      fetchEvals({
        status: statusFilter,
        // Fetch one extra row so we can detect whether a next page exists
        // without needing a separate count endpoint.
        limit: pageSize + 1,
        offset: pageIndex * pageSize,
      }),
    refetchInterval: 5_000,
  })

  const hasNextPage = (data?.length ?? 0) > pageSize
  const pageRows = useMemo(() => (data ?? []).slice(0, pageSize), [data, pageSize])

  // Client-side name filter (applied within the current page only)
  const filtered = useMemo(() => {
    const q = nameFilter.trim().toLowerCase()
    return q ? pageRows.filter((r) => r.name.toLowerCase().includes(q)) : pageRows
  }, [pageRows, nameFilter])

  const table = useReactTable({
    data: filtered,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const hasFilters = !!nameFilter.trim() || statusFilter !== null
  const currentStatusLabel = STATUSES.find((s) => s.value === statusFilter)?.label ?? 'All statuses'

  const statusCounts = useMemo(() => {
    if (pageRows.length === 0) return null
    return {
      completed: pageRows.filter((r) => r.status === 'completed').length,
      running: pageRows.filter((r) => r.status === 'running').length,
      failed: pageRows.filter((r) => r.status === 'failed').length,
    }
  }, [pageRows])

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="flex items-center justify-between px-6 py-5 border-b border-zinc-200 dark:border-zinc-800">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Eval Runs</h1>
          <div className="flex items-center gap-3 mt-1 h-5">
            {!isLoading && data != null && statusCounts && (
              <>
                <span className="text-sm text-zinc-400 dark:text-zinc-500">
                  {pageRows.length} run{pageRows.length !== 1 ? 's' : ''} on this page
                </span>
                {statusCounts.completed > 0 && (
                  <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                    {statusCounts.completed} completed
                  </span>
                )}
                {statusCounts.running > 0 && (
                  <span className="text-xs text-blue-600 dark:text-blue-400 font-medium">
                    {statusCounts.running} running
                  </span>
                )}
                {statusCounts.failed > 0 && (
                  <span className="text-xs text-red-500 dark:text-red-400 font-medium">
                    {statusCounts.failed} failed
                  </span>
                )}
              </>
            )}
          </div>
        </div>
        <button
          onClick={() => setModalOpen(true)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-zinc-950 shadow-sm shadow-blue-600/20"
        >
          <Plus size={15} />
          New Eval Run
        </button>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 px-6 py-3.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/40">
        {/* Search */}
        <div className="relative flex-1 max-w-xs">
          <Search
            size={13}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400 pointer-events-none"
          />
          <input
            type="search"
            placeholder="Search by name…"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            className="w-full pl-8 pr-4 py-2 text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg text-zinc-800 dark:text-zinc-100 placeholder-zinc-400 outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all shadow-sm"
          />
        </div>

        {/* Status dropdown */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen((o) => !o)}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg text-zinc-600 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-600 hover:text-zinc-800 dark:hover:text-zinc-100 transition-all outline-none focus:ring-2 focus:ring-blue-500/40 shadow-sm whitespace-nowrap"
          >
            {currentStatusLabel}
            <ChevronDown
              size={13}
              className={cn(
                'text-zinc-400 transition-transform duration-150',
                dropdownOpen && 'rotate-180',
              )}
            />
          </button>
          {dropdownOpen && (
            <div className="absolute left-0 top-full mt-1.5 w-44 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-lg shadow-black/10 dark:shadow-black/40 overflow-hidden z-20">
              {STATUSES.map((s) => (
                <button
                  key={s.label}
                  onClick={() => {
                    setStatusFilter(s.value)
                    setDropdownOpen(false)
                  }}
                  className={cn(
                    'w-full text-left px-3.5 py-2.5 text-sm transition-colors',
                    s.value === statusFilter
                      ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium'
                      : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100',
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1" />

        {/* Manual refresh */}
        {!isError && (
          <button
            onClick={() => void refetch()}
            title="Refresh"
            className="p-2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
          </button>
        )}
      </div>

      {/* Content area */}
      {isError ? (
        <div className="flex-1">
          <ErrorState onRetry={() => void refetch()} />
        </div>
      ) : (
        <div className="flex-1 overflow-auto scrollbar-thin">
          <table className="w-full">
            {/* Sticky header */}
            <thead className="sticky top-0 z-10 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((header) => (
                    <th
                      key={header.id}
                      className="px-4 py-3 text-left text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>

            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
              {isLoading ? (
                Array.from({ length: 7 }).map((_, i) => <TableRowSkeleton key={i} />)
              ) : table.getRowModel().rows.length === 0 ? (
                <EmptyState hasFilters={hasFilters} />
              ) : (
                table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => void navigate(`/evals/${row.original.run_id}`)}
                    className="group hover:bg-zinc-50 dark:hover:bg-zinc-900/60 cursor-pointer transition-colors"
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-4 py-3.5">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer / pagination */}
      {!isError && (
        <div className="flex items-center justify-between gap-4 px-6 py-3 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/40">
          {/* Page-size selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400 dark:text-zinc-500">Rows per page</span>
            <div className="relative" ref={pageSizeRef}>
              <button
                onClick={() => setPageSizeOpen((o) => !o)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-md text-zinc-600 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-600 transition-all outline-none focus:ring-2 focus:ring-blue-500/40 tabular-nums"
              >
                {pageSize}
                <ChevronDown
                  size={11}
                  className={cn(
                    'text-zinc-400 transition-transform duration-150',
                    pageSizeOpen && 'rotate-180',
                  )}
                />
              </button>
              {pageSizeOpen && (
                <div className="absolute left-0 bottom-full mb-1.5 w-20 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-lg shadow-black/10 dark:shadow-black/40 overflow-hidden z-20">
                  {PAGE_SIZES.map((n) => (
                    <button
                      key={n}
                      onClick={() => {
                        setPageSize(n)
                        setPageSizeOpen(false)
                      }}
                      className={cn(
                        'w-full text-left px-3 py-1.5 text-xs tabular-nums transition-colors',
                        n === pageSize
                          ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium'
                          : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800',
                      )}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Range + prev/next */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-zinc-400 dark:text-zinc-500 tabular-nums">
              {pageRows.length === 0
                ? '0 results'
                : `${pageIndex * pageSize + 1}–${pageIndex * pageSize + pageRows.length}`}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
                disabled={pageIndex === 0 || isLoading}
                className="p-1.5 rounded-md text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                aria-label="Previous page"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="text-xs text-zinc-500 dark:text-zinc-400 tabular-nums px-2">
                Page {pageIndex + 1}
              </span>
              <button
                onClick={() => setPageIndex((i) => i + 1)}
                disabled={!hasNextPage || isLoading}
                className="p-1.5 rounded-md text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                aria-label="Next page"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      <NewEvalModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  )
}
