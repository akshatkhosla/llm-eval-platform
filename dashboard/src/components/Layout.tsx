import { useState, useEffect } from 'react'
import { Outlet, useLocation, Link } from 'react-router-dom'
import { ChevronRight, Home } from 'lucide-react'
import { Sidebar } from './Sidebar'

const ROUTE_LABELS: Record<string, string> = {
  evals: 'Eval Runs',
  compare: 'Compare',
  trends: 'Trends',
}

export function Layout() {
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    const stored = localStorage.getItem('theme')
    return stored !== 'light'
  })

  useEffect(() => {
    const html = document.documentElement
    if (darkMode) {
      html.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    } else {
      html.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }
  }, [darkMode])

  const location = useLocation()
  const crumbs = location.pathname
    .split('/')
    .filter(Boolean)
    .reduce<{ label: string; to: string }[]>((acc, segment) => {
      const to = (acc[acc.length - 1]?.to ?? '') + '/' + segment
      return [...acc, { label: ROUTE_LABELS[segment] ?? segment, to }]
    }, [])

  return (
    <div className="flex min-h-screen bg-white dark:bg-zinc-950">
      <Sidebar darkMode={darkMode} onToggleDark={() => setDarkMode((d) => !d)} />
      <main className="flex-1 flex flex-col min-h-screen overflow-hidden">
        {/* Breadcrumbs */}
        {crumbs.length > 0 && (
          <nav className="flex items-center gap-1.5 px-6 py-3 border-b border-zinc-200 dark:border-zinc-800 text-sm text-zinc-400">
            <Link
              to="/"
              className="hover:text-zinc-700 dark:hover:text-zinc-100 transition-colors"
            >
              <Home size={13} />
            </Link>
            {crumbs.map((crumb, i) => (
              <span key={crumb.to} className="flex items-center gap-1.5">
                <ChevronRight size={12} className="text-zinc-300 dark:text-zinc-700" />
                {i === crumbs.length - 1 ? (
                  <span className="text-zinc-700 dark:text-zinc-200 font-medium">
                    {crumb.label}
                  </span>
                ) : (
                  <Link
                    to={crumb.to}
                    className="hover:text-zinc-700 dark:hover:text-zinc-100 transition-colors"
                  >
                    {crumb.label}
                  </Link>
                )}
              </span>
            ))}
          </nav>
        )}
        {/* Page content */}
        <div className="flex-1 overflow-y-auto scrollbar-thin">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
