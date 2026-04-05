import { useState, useEffect, useRef } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { Settings, LogOut, Bot, BarChart2, ChevronRight, Plus, MoreHorizontal, FolderOpen, MessageSquare } from 'lucide-react'
import { useAuthStore } from '../../store/authStore'
import { listProjects, type ProjectOut } from '../../api/projects'
import { listConversations, assignConversation, type ConversationOut } from '../../api/chat'

interface SidebarProps {
  activeConvId: string | null
  onConversationSelect: (id: string) => void
  onNewConversation: (projectId?: string | null) => void
  refreshKey?: number
}

export function Sidebar({ activeConvId, onConversationSelect, onNewConversation, refreshKey }: SidebarProps) {
  const logout = useAuthStore((s) => s.logout)
  const token = useAuthStore((s) => s.token)
  const navigate = useNavigate()

  const [projects, setProjects] = useState<ProjectOut[]>([])
  const [conversations, setConversations] = useState<ConversationOut[]>([])
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set())
  const [contextMenu, setContextMenu] = useState<{ convId: string; x: number; y: number } | null>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!token) return
    Promise.all([listProjects(), listConversations()]).then(([projs, convs]) => {
      setProjects(projs)
      setConversations(convs)
    }).catch(() => {})
  }, [refreshKey, token])

  // Zavřít context menu při kliknutí mimo
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target as Node)) {
        setContextMenu(null)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  function toggleProject(id: string) {
    setExpandedProjects((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function openContextMenu(e: React.MouseEvent, convId: string) {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ convId, x: e.clientX, y: e.clientY })
  }

  async function handleAssign(projectId: string | null) {
    if (!contextMenu) return
    try {
      await assignConversation(contextMenu.convId, projectId)
      setContextMenu(null)
      const [projs, convs] = await Promise.all([listProjects(), listConversations()])
      setProjects(projs)
      setConversations(convs)
    } catch {
      // ignore
    }
  }

  const globalConvs = conversations.filter((c) => !c.project_id)

  return (
    <aside className="w-52 flex flex-col bg-[var(--surface)] border-r border-[var(--border)] shrink-0 overflow-hidden">
      {/* Header — logo + název */}
      <div className="flex items-center gap-2 px-3 py-3 border-b border-[var(--border)]">
        <div className="p-1.5 rounded-lg bg-[var(--accent)]/10">
          <Bot size={16} className="text-[var(--accent)]" />
        </div>
        <span className="text-sm font-semibold text-[var(--text)]">dautuu</span>
      </div>

      {/* Scrollovatelný obsah */}
      <div className="flex-1 overflow-y-auto py-2 flex flex-col gap-1">

        {/* Projekty */}
        <div className="px-2">
          <div className="flex items-center justify-between px-2 py-1 mb-0.5">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">Projekty</span>
            <NavLink
              to="/settings/projects"
              title="Spravovat projekty"
              className="p-0.5 rounded text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
            >
              <Settings size={11} />
            </NavLink>
          </div>

          {projects.map((proj) => {
            const projConvs = conversations.filter((c) => c.project_id === proj.id)
            const isExpanded = expandedProjects.has(proj.id)
            return (
              <div key={proj.id}>
                <button
                  onClick={() => toggleProject(proj.id)}
                  className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors group"
                >
                  <ChevronRight
                    size={12}
                    className={`shrink-0 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                  />
                  <FolderOpen size={13} className="shrink-0 text-[var(--accent)]/70" />
                  <span className="flex-1 text-left truncate">{proj.name}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); onNewConversation(proj.id) }}
                    title="Nová konverzace v projektu"
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[var(--surface)] transition-opacity"
                  >
                    <Plus size={11} />
                  </button>
                </button>
                {isExpanded && (
                  <div className="ml-4 flex flex-col gap-0.5 mb-1">
                    {projConvs.length === 0 && (
                      <span className="text-[10px] text-[var(--text-muted)] px-2 py-1">Žádné konverzace</span>
                    )}
                    {projConvs.map((conv) => (
                      <ConvItem
                        key={conv.id}
                        conv={conv}
                        isActive={conv.id === activeConvId}
                        onSelect={onConversationSelect}
                        onContextMenu={openContextMenu}
                      />
                    ))}
                  </div>
                )}
              </div>
            )
          })}

          {projects.length === 0 && (
            <p className="text-[10px] text-[var(--text-muted)] px-2 py-1">
              Zatím žádné projekty.{' '}
              <NavLink to="/settings/projects" className="underline hover:text-[var(--text)]">Vytvořit</NavLink>
            </p>
          )}
        </div>

        {/* Globální konverzace */}
        <div className="px-2 mt-2">
          <div className="flex items-center justify-between px-2 py-1 mb-0.5">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">Globální</span>
            <button
              onClick={() => onNewConversation(null)}
              title="Nová globální konverzace"
              className="p-0.5 rounded text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
            >
              <Plus size={11} />
            </button>
          </div>
          {globalConvs.length === 0 && (
            <p className="text-[10px] text-[var(--text-muted)] px-2 py-1">Žádné konverzace</p>
          )}
          {globalConvs.map((conv) => (
            <ConvItem
              key={conv.id}
              conv={conv}
              isActive={conv.id === activeConvId}
              onSelect={onConversationSelect}
              onContextMenu={openContextMenu}
            />
          ))}
        </div>
      </div>

      {/* Bottom nav */}
      <div className="border-t border-[var(--border)] py-2 px-2 flex flex-col gap-0.5">
        <NavLink
          to="/usage"
          className={({ isActive }) =>
            [
              'flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors',
              isActive
                ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]',
            ].join(' ')
          }
        >
          <BarChart2 size={14} />
          Spotřeba
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            [
              'flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors',
              isActive
                ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]',
            ].join(' ')
          }
        >
          <Settings size={14} />
          Nastavení
        </NavLink>
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--danger)]/10 transition-colors"
        >
          <LogOut size={14} />
          Odhlásit se
        </button>
      </div>

      {/* Context menu pro přeřazení konverzace */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          style={{ position: 'fixed', top: contextMenu.y, left: contextMenu.x, zIndex: 100 }}
          className="min-w-[170px] rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-xl py-1 text-xs"
        >
          <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)] mb-1">
            Přeřadit do projektu
          </div>
          <button
            onClick={() => handleAssign(null)}
            className="w-full text-left px-3 py-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)] transition-colors flex items-center gap-2"
          >
            <MessageSquare size={12} />
            Globální (bez projektu)
          </button>
          {projects.map((proj) => (
            <button
              key={proj.id}
              onClick={() => handleAssign(proj.id)}
              className="w-full text-left px-3 py-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)] transition-colors flex items-center gap-2"
            >
              <FolderOpen size={12} className="text-[var(--accent)]/70" />
              {proj.name}
            </button>
          ))}
        </div>
      )}
    </aside>
  )
}

// ---------------------------------------------------------------------------
// ConvItem — řádek konverzace
// ---------------------------------------------------------------------------

function ConvItem({
  conv,
  isActive,
  onSelect,
  onContextMenu,
}: {
  conv: ConversationOut
  isActive: boolean
  onSelect: (id: string) => void
  onContextMenu: (e: React.MouseEvent, id: string) => void
}) {
  return (
    <div
      className={[
        'group flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs cursor-pointer transition-colors',
        isActive
          ? 'bg-[var(--accent)]/15 text-[var(--text)]'
          : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]',
      ].join(' ')}
      onClick={() => onSelect(conv.id)}
      onContextMenu={(e) => onContextMenu(e, conv.id)}
    >
      <span className="flex-1 truncate">{conv.title}</span>
      <button
        onMouseDown={(e) => { e.stopPropagation(); onContextMenu(e, conv.id) }}
        className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[var(--surface)] transition-opacity shrink-0"
        title="Přeřadit"
      >
        <MoreHorizontal size={11} />
      </button>
    </div>
  )
}
