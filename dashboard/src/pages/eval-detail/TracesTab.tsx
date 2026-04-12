import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ChevronDown, AlertTriangle, Activity } from 'lucide-react'
import { fetchEvalTraces } from '../../lib/api'
import type { TraceSpan } from '../../types'
import { cn } from '../../lib/utils'

// ── Helpers ────────────────────────────────────────────────────────────

function fmtDuration(ms: number | null): string {
  if (ms === null) return '—'
  if (ms < 1) return `${(ms * 1000).toFixed(0)}µs`
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function statusDot(status: string): string {
  if (status === 'ok' || status === 'passed' || status === 'success') return 'bg-emerald-500'
  if (status === 'error') return 'bg-red-500'
  if (status === 'partial') return 'bg-amber-500'
  return 'bg-zinc-400 dark:bg-zinc-600'
}

function spanLabel(name: string): string {
  // Make raw internal names more readable
  const labels: Record<string, string> = {
    eval_run: 'Eval Run',
    sample_execution: 'Sample',
    llm_call: 'LLM Call',
    judge_execution: 'Judge',
  }
  return labels[name] ?? name
}

// ── Attributes panel ───────────────────────────────────────────────────

function AttributePanel({
  attributes,
  indentPx,
}: {
  attributes: Record<string, unknown>
  indentPx: number
}) {
  const entries = Object.entries(attributes)
  if (entries.length === 0) return null
  return (
    <div
      className="mb-1 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg p-3 text-xs font-mono space-y-0.5"
      style={{ marginLeft: indentPx, marginRight: 16 }}
    >
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2 leading-relaxed">
          <span className="text-blue-500 dark:text-blue-400 flex-shrink-0">{k}:</span>
          <span className="text-zinc-600 dark:text-zinc-400 break-all">
            {typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}
          </span>
        </div>
      ))}
    </div>
  )
}

// ── Span node (recursive) ─────────────────────────────────────────────

function SpanNode({
  span,
  totalMs,
  depth,
}: {
  span: TraceSpan
  totalMs: number
  depth: number
}) {
  const [open, setOpen] = useState(depth < 2)
  const [attrOpen, setAttrOpen] = useState(false)

  const hasChildren = span.children.length > 0
  const hasAttrs = Object.keys(span.attributes).length > 0
  const pct = totalMs > 0 && span.duration_ms != null ? (span.duration_ms / totalMs) * 100 : 0
  const indentPx = depth * 20 + 12

  return (
    <div>
      {/* Row */}
      <div
        className="flex items-center gap-2 py-2 pr-4 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors cursor-pointer group"
        style={{ paddingLeft: indentPx }}
        onClick={() => {
          if (hasChildren) setOpen((o) => !o)
          else setAttrOpen((o) => !o)
        }}
      >
        {/* Expand / leaf icon */}
        <div className="w-4 flex-shrink-0 flex items-center justify-center">
          {hasChildren ? (
            open ? (
              <ChevronDown size={13} className="text-zinc-400" />
            ) : (
              <ChevronRight size={13} className="text-zinc-400" />
            )
          ) : (
            <span className="block w-1.5 h-1.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />
          )}
        </div>

        {/* Status dot */}
        <span className={cn('w-2 h-2 rounded-full flex-shrink-0', statusDot(span.status))} />

        {/* Name */}
        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300 min-w-[120px] flex-shrink-0">
          {spanLabel(span.name)}
        </span>

        {/* Duration bar */}
        <div className="flex-1 flex items-center gap-2 min-w-0">
          <div className="flex-1 h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden max-w-[200px]">
            {pct > 0 && (
              <div
                className="h-full bg-blue-400/50 rounded-full"
                style={{ width: `${pct}%` }}
              />
            )}
          </div>
          <span className="text-xs tabular-nums text-zinc-400 dark:text-zinc-500 w-16 text-right flex-shrink-0">
            {fmtDuration(span.duration_ms)}
          </span>
        </div>

        {/* Attrs toggle for leaf nodes */}
        {hasAttrs && !hasChildren && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              setAttrOpen((o) => !o)
            }}
            className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 opacity-0 group-hover:opacity-100 transition-opacity px-1.5 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 flex-shrink-0"
          >
            {attrOpen ? 'hide' : 'attrs'}
          </button>
        )}

        {/* Attrs toggle for branch nodes (show on hover) */}
        {hasAttrs && hasChildren && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              setAttrOpen((o) => !o)
            }}
            className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 opacity-0 group-hover:opacity-100 transition-opacity px-1.5 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 flex-shrink-0"
          >
            {attrOpen ? 'hide' : 'attrs'}
          </button>
        )}
      </div>

      {/* Attribute panel */}
      {attrOpen && (
        <AttributePanel attributes={span.attributes} indentPx={indentPx + 24} />
      )}

      {/* Children */}
      {open &&
        span.children.map((child) => (
          <SpanNode key={child.span_id} span={child} totalMs={totalMs} depth={depth + 1} />
        ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────

export function TracesTab({ runId }: { runId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['eval-traces', runId],
    queryFn: () => fetchEvalTraces(runId),
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24 px-4">
        <div className="w-12 h-12 rounded-xl bg-amber-50 dark:bg-amber-500/10 flex items-center justify-center mb-4">
          <AlertTriangle size={20} className="text-amber-500 dark:text-amber-400" />
        </div>
        <p className="text-base font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
          No trace data
        </p>
        <p className="text-sm text-zinc-400 dark:text-zinc-500 text-center max-w-xs leading-relaxed">
          Traces are stored when a run completes. Check back after this run finishes.
        </p>
      </div>
    )
  }

  return (
    <div className="px-6 py-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity size={15} className="text-zinc-400" />
          <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            Execution Trace
          </h3>
        </div>
        <div className="flex items-center gap-4 text-xs text-zinc-400 dark:text-zinc-500">
          <span>{data.total_spans} spans</span>
          <span className="tabular-nums">{fmtDuration(data.total_duration_ms)} total</span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mb-3 text-xs text-zinc-400 dark:text-zinc-500">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          ok
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-amber-500" />
          partial
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-red-500" />
          error
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-8 bg-blue-400/50 rounded-full" />
          relative duration
        </span>
      </div>

      {/* Tree */}
      <div className="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-2">
        <SpanNode
          span={data.root_span}
          totalMs={data.total_duration_ms}
          depth={0}
        />
      </div>
    </div>
  )
}
