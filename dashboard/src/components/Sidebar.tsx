import { NavLink } from 'react-router-dom'
import { ListChecks, GitCompare, TrendingUp, Zap, Sun, Moon } from 'lucide-react'
import { cn } from '../lib/utils'

const NAV_ITEMS = [
  { to: '/evals', label: 'Eval Runs', icon: ListChecks },
  { to: '/compare', label: 'Compare', icon: GitCompare },
  { to: '/trends', label: 'Trends', icon: TrendingUp },
]

interface Props {
  darkMode: boolean
  onToggleDark: () => void
}

export function Sidebar({ darkMode, onToggleDark }: Props) {
  return (
    <aside className="w-60 flex-shrink-0 bg-zinc-50 border-r border-zinc-200 dark:bg-zinc-900 dark:border-zinc-800 flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-zinc-200 dark:border-zinc-800">
        <div className="h-7 w-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-blue-600/30">
          <Zap size={14} className="text-white" />
        </div>
        <div>
          <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 leading-none">
            LLM Eval
          </div>
          <div className="text-xs text-zinc-400 dark:text-zinc-500 mt-0.5">Platform</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto scrollbar-thin">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                isActive
                  ? 'bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800/60',
              )
            }
          >
            <Icon size={16} className="flex-shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Dark mode toggle */}
      <div className="px-3 py-4 border-t border-zinc-200 dark:border-zinc-800">
        <button
          onClick={onToggleDark}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800/60 transition-colors"
        >
          {darkMode ? <Sun size={16} /> : <Moon size={16} />}
          {darkMode ? 'Light mode' : 'Dark mode'}
        </button>
      </div>
    </aside>
  )
}
