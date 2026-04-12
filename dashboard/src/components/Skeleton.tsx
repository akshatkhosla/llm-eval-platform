import type { CSSProperties } from 'react'
import { cn } from '../lib/utils'

export function Skeleton({
  className,
  style,
}: {
  className?: string
  style?: CSSProperties
}) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-800', className)}
      style={style}
    />
  )
}

const COL_WIDTHS = [180, 88, 72, 130, 96, 52, 56, 60, 88]

export function TableRowSkeleton() {
  return (
    <tr className="border-b border-zinc-100 dark:border-zinc-800/60">
      {COL_WIDTHS.map((w, i) => (
        <td key={i} className="px-4 py-3.5">
          <Skeleton className="h-4 rounded" style={{ width: `${w}px` }} />
        </td>
      ))}
    </tr>
  )
}
