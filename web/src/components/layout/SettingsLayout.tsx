import { NavLink, Outlet, Navigate, useLocation } from 'react-router-dom'
import { Cpu, Key, Server, Plug, FolderOpen } from 'lucide-react'

const tabs = [
  { to: '/settings/model', icon: Cpu, label: 'Model' },
  { to: '/settings/projects', icon: FolderOpen, label: 'Projekty' },
  { to: '/settings/mcp', icon: Key, label: 'MCP Server' },
  { to: '/settings/mcp-clients', icon: Plug, label: 'MCP Klienti' },
  { to: '/settings/connection', icon: Server, label: 'Připojení' },
]

export function SettingsLayout() {
  const { pathname } = useLocation()

  // /settings → přesměruj na první tab
  if (pathname === '/settings' || pathname === '/settings/') {
    return <Navigate to="/settings/model" replace />
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 pb-16 flex flex-col gap-6">
      <h1 className="text-xl font-semibold text-[var(--text)]">Nastavení</h1>

      {/* Tab bar */}
      <nav className="flex gap-1 border-b border-[var(--border)]">
        {tabs.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              [
                'flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
                isActive
                  ? 'border-[var(--accent)] text-[var(--accent)]'
                  : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text)]',
              ].join(' ')
            }
          >
            <Icon size={14} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Obsah aktivního tabu */}
      <Outlet />
    </div>
  )
}
