import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, AlertTriangle, RefreshCw } from 'lucide-react'
import { fetchEvalDetail } from '../lib/api'
import type { EvalRunDetail } from '../types'
import { StatusBadge } from '../components/StatusBadge'
import { OverviewTab } from './eval-detail/OverviewTab'
import { ResultsTab } from './eval-detail/ResultsTab'
import { TracesTab } from './eval-detail/TracesTab'
import { ConfigTab } from './eval-detail/ConfigTab'
import { cn, relativeTime } from '../lib/utils'

type Tab = 'overview' | 'results' | 'traces' | 'config'

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'results', label: 'Results' },
  { id: 'traces', label: 'Traces' },
  { id: 'config', label: 'Config' },
]

function LoadingSkeleton() {
  return (
    <div className="animate-pulse px-6 py-5 space-y-4">
      <div className="h-4 w-20 bg-zinc-100 dark:bg-zinc-800 rounded" />
      <div className="h-7 w-72 bg-zinc-100 dark:bg-zinc-800 rounded-lg" />
      <div className="h-4 w-52 bg-zinc-100 dark:bg-zinc-800 rounded" />
    </div>
  )
}

export function EvalDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<Tab>('overview')

  const { data: run, isLoading, isError, refetch } = useQuery({
    queryKey: ['eval', id],
    queryFn: () => fetchEvalDetail(id!),
    refetchInterval: (query) => {
      const data = query.state.data as EvalRunDetail | undefined
      return data?.status === 'running' ? 2_000 : false
    },
    enabled: !!id,
  })

  if (isLoading) return <LoadingSkeleton />

  if (isError || !run) {
    return (
      <div className="flex flex-col items-center justify-center py-24 px-4">
        <div className="w-12 h-12 rounded-xl bg-red-50 dark:bg-red-500/10 flex items-center justify-center mb-4">
          <AlertTriangle size={20} className="text-red-500 dark:text-red-400" />
        </div>
        <p className="text-base font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
          Failed to load eval run
        </p>
        <p className="text-sm text-zinc-400 dark:text-zinc-500 mb-6">
          Could not fetch run details. The run may not exist.
        </p>
        <button
          onClick={() => void refetch()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors"
        >
          <RefreshCw size={14} />
          Try again
        </button>
      </div>
    )
  }

  const progress =
    run.total_samples != null && run.total_samples > 0
      ? Math.min(100, (run.completed_samples / run.total_samples) * 100)
      : 0

  return (
    <div className="flex flex-col min-h-full">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="px-6 pt-5 pb-4 border-b border-zinc-200 dark:border-zinc-800">
        <button
          onClick={() => void navigate('/evals')}
          className="inline-flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 mb-3 transition-colors"
        >
          <ArrowLeft size={12} />
          All runs
        </button>

        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              {run.name}
            </h1>
            <div className="flex items-center gap-2.5 mt-1.5 flex-wrap text-sm">
              <span className="font-mono text-zinc-500 dark:text-zinc-400 text-xs">
                {run.provider} / {run.model}
              </span>
              <span className="text-zinc-300 dark:text-zinc-700">·</span>
              <span className="text-zinc-400 dark:text-zinc-500">
                Created {relativeTime(run.created_at)}
              </span>
              {run.completed_at && (
                <>
                  <span className="text-zinc-300 dark:text-zinc-700">·</span>
                  <span className="text-zinc-400 dark:text-zinc-500">
                    Finished {relativeTime(run.completed_at)}
                  </span>
                </>
              )}
            </div>
          </div>
          <StatusBadge status={run.status} />
        </div>

        {/* Progress bar — only while running and total_samples is known */}
        {run.status === 'running' && run.total_samples != null && (
          <div className="mt-4 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-400 dark:text-zinc-500">
                {run.completed_samples} / {run.total_samples} samples
              </span>
              <span className="text-xs font-semibold text-blue-500 tabular-nums">
                {Math.round(progress)}%
              </span>
            </div>
            <div className="h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* ── Tab bar ─────────────────────────────────────────────────── */}
      <div className="flex gap-0 border-b border-zinc-200 dark:border-zinc-800 px-6 bg-zinc-50/60 dark:bg-zinc-900/40">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'px-4 py-3 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab.id
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:border-zinc-300 dark:hover:border-zinc-700',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Tab content ─────────────────────────────────────────────── */}
      <div className="flex-1">
        {activeTab === 'overview' && <OverviewTab run={run} />}
        {activeTab === 'results' && <ResultsTab runId={run.run_id} />}
        {activeTab === 'traces' && <TracesTab runId={run.run_id} />}
        {activeTab === 'config' && (
          <ConfigTab run={run} onRerun={(newId) => void navigate(`/evals/${newId}`)} />
        )}
      </div>
    </div>
  )
}
