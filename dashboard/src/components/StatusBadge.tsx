import type { EvalStatus } from '../types'
import { cn } from '../lib/utils'

const CONFIG: Record<EvalStatus, { label: string; dot: string; badge: string }> = {
  pending: {
    label: 'Pending',
    dot: 'bg-zinc-400',
    badge: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/25 dark:bg-zinc-500/15 dark:text-zinc-400',
  },
  running: {
    label: 'Running',
    dot: 'bg-blue-400 animate-pulse',
    badge: 'bg-blue-500/15 text-blue-600 border-blue-500/25 dark:text-blue-400',
  },
  completed: {
    label: 'Completed',
    dot: 'bg-emerald-500',
    badge: 'bg-emerald-500/15 text-emerald-700 border-emerald-500/25 dark:text-emerald-400',
  },
  failed: {
    label: 'Failed',
    dot: 'bg-red-500',
    badge: 'bg-red-500/15 text-red-700 border-red-500/25 dark:text-red-400',
  },
}

export function StatusBadge({ status }: { status: string }) {
  const s = (Object.keys(CONFIG).includes(status) ? status : 'pending') as EvalStatus
  const cfg = CONFIG[s]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        cfg.badge,
      )}
    >
      <span className={cn('h-1.5 w-1.5 flex-shrink-0 rounded-full', cfg.dot)} />
      {cfg.label}
    </span>
  )
}
