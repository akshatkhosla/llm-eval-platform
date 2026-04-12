import { useState, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table'
import { useQuery } from '@tanstack/react-query'
import { Plus, Search, RefreshCw, ChevronDown, BarChart2, AlertTriangle } from 'lucide-react'
import { fetchEvals } from '../lib/api'
import type { EvalRunSummary } from '../types'
import { StatusBadge } from '../components/StatusBadge'
import { TableRowSkeleton } from '../components/Skeleton'
import { NewEvalModal } from '../components/NewEvalModal'
import { cn, relativeTime, formatDuration, formatTokens } from '../lib/utils'

// ── Sub-components ──────────────────────────────────────────────────────────

function SamplesProgress({
  completed,
  total,
}: {
  completed: number
  total: number | null
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
            isComplete ? 'bg-emerald-500' : 'bg-blue-500',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-zinc-500 dark:text-zinc-400 tabular-nums whitespace-nowrap">
        {completed}/{total}
      </span>
    </div>
  )
}

function ScoreCell({ score }: { score: number | null }) {
  if (score === null)
    return (
      <span
        className="text-sm text-zinc-300 dark:text-zinc-600"
        title="Available in run detail"
      >
        —
      </span>
    )
  const color =
    score >= 7
      ? 'text-emerald-600 dark:text-emerald-400'
      : score >= 4
        ? 'text-amber-600 dark:text-amber-400'
        : 'text-red-600 dark:text-red-400'
  return (
    <span className={cn('text-sm font-medium tabular-nums', color)}>{score.toFixed(1)}</span>
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
  col.accessor('status', {
    header: 'Status',
    cell: (info) => <StatusBadge status={info.getValue()} />,
  }),
  col.accessor('provider', {
    header: 'Provider',
    cell: (info) => (
      <span className="text-sm text-zinc-700 dark:text-zinc-300 capitalize">
        {info.getValue()}
      </span>
    ),
  }),
  col.accessor('model', {
    header: 'Model',
    cell: (info) => (
      <span className="text-sm font-mono text-zinc-500 dark:text-zinc-400 truncate max-w-[160px] block">
        {info.getValue()}
      </span>
    ),
  }),
  col.display({
    id: 'samples',
    header: 'Samples',
    cell: ({ row }) => (
      <SamplesProgress
        completed={row.original.completed_samples}
        total={row.original.total_samples}
      />
    ),
  }),
  col.display({
    id: 'avg_score',
    header: 'Avg Score',
    cell: () => <ScoreCell score={null} />,
  }),
  col.accessor('total_tokens', {
    header: 'Tokens',
    cell: (info) => (
      <span className="text-sm text-zinc-500 dark:text-zinc-400 tabular-nums">
        {formatTokens(info.getValue())}
      </span>
    ),
  }),
  col.accessor('total_latency_ms', {
    header: 'Duration',
    cell: (info) => (
      <span className="text-sm text-zinc-500 dark:text-zinc-400 tabular-nums">
        {formatDuration(info.getValue())}
      </span>
    ),
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
  const dropdownRef = useRef<HTMLDivElement>(null)

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

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['evals', statusFilter],
    queryFn: () => fetchEvals({ status: statusFilter }),
    refetchInterval: 5_000,
  })

  // Client-side name filter
  const filtered = useMemo(() => {
    if (!data) return []
    const q = nameFilter.trim().toLowerCase()
    return q ? data.filter((r) => r.name.toLowerCase().includes(q)) : data
  }, [data, nameFilter])

  const table = useReactTable({
    data: filtered,
    columns: COLUMNS,
    getCoreRowModel: getCoreRowModel(),
  })

  const hasFilters = !!nameFilter.trim() || statusFilter !== null
  const currentStatusLabel = STATUSES.find((s) => s.value === statusFilter)?.label ?? 'All statuses'

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="flex items-center justify-between px-6 py-5 border-b border-zinc-200 dark:border-zinc-800">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Eval Runs</h1>
          <p className="text-sm text-zinc-400 dark:text-zinc-500 mt-0.5 h-5">
            {!isLoading && data != null && (
              <>
                {data.length} run{data.length !== 1 ? 's' : ''} total
              </>
            )}
          </p>
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
                    className="hover:bg-zinc-50 dark:hover:bg-zinc-900/60 cursor-pointer transition-colors"
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

      {/* Footer */}
      {!isLoading && !isError && filtered.length > 0 && (
        <div className="flex items-center justify-between px-6 py-3 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/40">
          <span className="text-xs text-zinc-400 dark:text-zinc-500">
            Showing{' '}
            <span className="text-zinc-600 dark:text-zinc-300 font-medium">{filtered.length}</span>
            {data && filtered.length !== data.length && (
              <> of <span className="text-zinc-600 dark:text-zinc-300 font-medium">{data.length}</span></>
            )}{' '}
            run{filtered.length !== 1 ? 's' : ''}
          </span>
          <span className="text-xs text-zinc-300 dark:text-zinc-700">Auto-refreshes every 5s</span>
        </div>
      )}

      <NewEvalModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  )
}
