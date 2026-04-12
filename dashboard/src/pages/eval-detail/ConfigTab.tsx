import { useState, useCallback } from 'react'
import { Copy, Check, Play, AlertTriangle } from 'lucide-react'
import { rerunEval } from '../../lib/api'
import type { EvalRunDetail } from '../../types'

// ── YAML syntax highlighter ───────────────────────────────────────────
//
// Line-by-line tokenizer — no external parser needed.
// Handles: keys, strings (quoted/unquoted), numbers, booleans, null,
// comments, list bullets, and block scalar indicators.

function YamlValue({ raw }: { raw: string }) {
  const t = raw.trim()
  const lead = raw.match(/^(\s*)/)?.[1] ?? ''

  if (!t) return <span>{raw}</span>

  // Quoted string
  if (/^["'].*["']$/.test(t)) {
    return (
      <>
        <span>{lead}</span>
        <span style={{ color: '#86efac' }}>{t}</span>
      </>
    )
  }
  // Integer or float
  if (/^-?\d+(\.\d+)?$/.test(t)) {
    return (
      <>
        <span>{lead}</span>
        <span style={{ color: '#fbbf24' }}>{t}</span>
      </>
    )
  }
  // Boolean
  if (/^(true|false|yes|no|on|off)$/i.test(t)) {
    return (
      <>
        <span>{lead}</span>
        <span style={{ color: '#c084fc' }}>{t}</span>
      </>
    )
  }
  // Null / tilde
  if (/^(null|~)$/i.test(t)) {
    return (
      <>
        <span>{lead}</span>
        <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>{t}</span>
      </>
    )
  }
  // Unquoted string value
  return (
    <>
      <span>{lead}</span>
      <span style={{ color: '#86efac' }}>{t}</span>
    </>
  )
}

function YamlLine({ line }: { line: string }) {
  // Comment
  if (/^\s*#/.test(line)) {
    return <span style={{ color: '#52525b' }}>{line}</span>
  }

  // Block scalar indicator (| or >) on its own after colon
  // Key: value — or bare key: (block scalar start)
  const keyMatch = line.match(/^(\s*)([\w._/-]+)(\s*:\s*)(.*)$/)
  if (keyMatch) {
    const [, indent, key, colon, rest] = keyMatch
    return (
      <>
        <span>{indent}</span>
        <span style={{ color: '#93c5fd' }}>{key}</span>
        <span style={{ color: '#52525b' }}>{colon}</span>
        <YamlValue raw={rest} />
      </>
    )
  }

  // List item bullet
  const listMatch = line.match(/^(\s*-\s*)(.*)$/)
  if (listMatch) {
    const [, bullet, rest] = listMatch
    return (
      <>
        <span style={{ color: '#52525b' }}>{bullet}</span>
        <YamlValue raw={rest} />
      </>
    )
  }

  return <span style={{ color: '#a1a1aa' }}>{line}</span>
}

// ── Main component ────────────────────────────────────────────────────

export function ConfigTab({
  run,
  onRerun,
}: {
  run: EvalRunDetail
  onRerun: (newId: string) => void
}) {
  const [copied, setCopied] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [rerunError, setRerunError] = useState<string | null>(null)

  const yaml = run.config_yaml ?? '# No configuration stored for this run.'
  const lines = yaml.split('\n')

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(yaml)
    setCopied(true)
    setTimeout(() => setCopied(false), 2_000)
  }, [yaml])

  const handleRerun = useCallback(async () => {
    setRerunning(true)
    setRerunError(null)
    try {
      const res = await rerunEval(run.run_id)
      onRerun(res.run_id)
    } catch (err) {
      setRerunError(err instanceof Error ? err.message : 'Rerun failed')
      setRerunning(false)
    }
  }, [run.run_id, onRerun])

  return (
    <div className="px-6 py-5">
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          Run Configuration
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void handleCopy()}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors"
          >
            {copied ? (
              <Check size={12} className="text-emerald-500" />
            ) : (
              <Copy size={12} />
            )}
            {copied ? 'Copied!' : 'Copy'}
          </button>

          <button
            onClick={() => void handleRerun()}
            disabled={rerunning}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-zinc-950"
          >
            <Play size={11} className={rerunning ? 'animate-pulse' : ''} />
            {rerunning ? 'Starting…' : 'Re-run'}
          </button>
        </div>
      </div>

      {/* Error banner */}
      {rerunError && (
        <div className="mb-4 flex items-center gap-2 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-lg px-3 py-2.5 text-sm text-red-600 dark:text-red-400">
          <AlertTriangle size={14} className="flex-shrink-0" />
          <span>{rerunError}</span>
        </div>
      )}

      {/* Code viewer */}
      <div className="bg-zinc-950 border border-zinc-800 rounded-xl overflow-hidden">
        {/* Title bar */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
          </div>
          <span className="text-xs text-zinc-500 font-mono">config.yaml</span>
          <span className="text-xs text-zinc-700 tabular-nums">{lines.length} lines</span>
        </div>

        {/* Lines */}
        <pre className="p-4 text-sm font-mono leading-[1.65] overflow-x-auto scrollbar-thin max-h-[600px] overflow-y-auto text-zinc-300">
          {lines.map((line, i) => (
            <div key={i} className="flex hover:bg-white/[0.02] rounded-sm">
              <span
                className="select-none text-right pr-5 flex-shrink-0 tabular-nums"
                style={{ color: '#3f3f46', minWidth: '2.5rem' }}
              >
                {i + 1}
              </span>
              <span className="flex-1 min-w-0">
                <YamlLine line={line} />
              </span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  )
}
