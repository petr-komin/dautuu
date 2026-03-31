import { NavLink, useNavigate } from 'react-router-dom'
import { MessageSquare, Settings, LogOut, Bot, BarChart2 } from 'lucide-react'
import { useAuthStore } from '../../store/authStore'

const navItems = [
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/usage', icon: BarChart2, label: 'Spotřeba' },
  { to: '/settings', icon: Settings, label: 'Nastavení' },
]

export function Sidebar() {
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <aside className="w-16 flex flex-col items-center py-4 gap-2 bg-[var(--surface)] border-r border-[var(--border)] shrink-0">
      {/* Logo */}
      <div className="mb-4 p-2 rounded-xl bg-[var(--accent)]/10">
        <Bot size={22} className="text-[var(--accent)]" />
      </div>

      {/* Nav */}
      <nav className="flex flex-col items-center gap-1 flex-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              [
                'p-2.5 rounded-lg transition-colors',
                isActive
                  ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]',
              ].join(' ')
            }
          >
            <Icon size={20} />
          </NavLink>
        ))}
      </nav>

      {/* Logout */}
      <button
        onClick={handleLogout}
        title="Odhlásit se"
        className="p-2.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--danger)]/10 transition-colors"
      >
        <LogOut size={20} />
      </button>
    </aside>
  )
}
