import { useState, useEffect } from 'react'
import { Plus, Trash2, PlugZap, ToggleLeft, ToggleRight, ChevronRight, Pencil, Check, X } from 'lucide-react'
import toast from 'react-hot-toast'

import { Button } from '../components/ui/Button'
import {
  listMcpServers,
  createMcpServer,
  updateMcpServer,
  deleteMcpServer,
  testMcpServer,
  type McpServerOut,
  type McpToolInfo,
} from '../api/mcpServers'

type TransportType = 'streamable_http' | 'sse'

interface ServerForm {
  name: string
  url: string
  authHeader: string
  transport_type: TransportType
}

const EMPTY_FORM: ServerForm = { name: '', url: '', authHeader: '', transport_type: 'streamable_http' }

function TransportSelect({
  value,
  onChange,
}: {
  value: TransportType
  onChange: (v: TransportType) => void
}) {
  return (
    <div className="flex gap-2">
      {(['streamable_http', 'sse'] as TransportType[]).map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => onChange(t)}
          className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
            value === t
              ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
              : 'border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--text-muted)]'
          }`}
        >
          {t === 'streamable_http' ? 'Streamable HTTP' : 'SSE'}
        </button>
      ))}
    </div>
  )
}

export function McpClientsPage() {
  const [servers, setServers] = useState<McpServerOut[]>([])
  const [loadingList, setLoadingList] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<ServerForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<ServerForm>(EMPTY_FORM)
  const [editSaving, setEditSaving] = useState(false)

  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, McpToolInfo[]>>({})
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    listMcpServers()
      .then(setServers)
      .catch(() => toast.error('Nepodařilo se načíst MCP servery'))
      .finally(() => setLoadingList(false))
  }, [])

  async function handleAdd() {
    if (!form.name.trim() || !form.url.trim()) {
      toast.error('Vyplň název a URL')
      return
    }
    setSaving(true)
    try {
      const headers: Record<string, string> = {}
      if (form.authHeader.trim()) {
        headers['Authorization'] = form.authHeader.trim()
      }
      const server = await createMcpServer({
        name: form.name.trim(),
        url: form.url.trim(),
        headers,
        enabled: true,
        transport_type: form.transport_type,
      })
      setServers((prev) => [...prev, server])
      setForm(EMPTY_FORM)
      setShowForm(false)
      toast.success('Server přidán')
    } catch {
      toast.error('Nepodařilo se přidat server')
    } finally {
      setSaving(false)
    }
  }

  function startEdit(server: McpServerOut) {
    setEditingId(server.id)
    setEditForm({
      name: server.name,
      url: server.url,
      authHeader: server.headers['Authorization'] ?? '',
      transport_type: server.transport_type,
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setEditForm(EMPTY_FORM)
  }

  async function handleSaveEdit(server: McpServerOut) {
    if (!editForm.name.trim() || !editForm.url.trim()) {
      toast.error('Vyplň název a URL')
      return
    }
    setEditSaving(true)
    try {
      const headers: Record<string, string> = {}
      if (editForm.authHeader.trim()) {
        headers['Authorization'] = editForm.authHeader.trim()
      }
      const updated = await updateMcpServer(server.id, {
        name: editForm.name.trim(),
        url: editForm.url.trim(),
        headers,
        transport_type: editForm.transport_type,
      })
      setServers((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
      setEditingId(null)
      toast.success('Server uložen')
    } catch {
      toast.error('Nepodařilo se uložit')
    } finally {
      setEditSaving(false)
    }
  }

  async function handleToggle(server: McpServerOut) {
    setTogglingId(server.id)
    try {
      const updated = await updateMcpServer(server.id, { enabled: !server.enabled })
      setServers((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
    } catch {
      toast.error('Nepodařilo se změnit stav')
    } finally {
      setTogglingId(null)
    }
  }

  async function handleDelete(id: string) {
    setDeletingId(id)
    try {
      await deleteMcpServer(id)
      setServers((prev) => prev.filter((s) => s.id !== id))
      setTestResults((prev) => {
        const r = { ...prev }
        delete r[id]
        return r
      })
      toast.success('Server smazán')
    } catch {
      toast.error('Nepodařilo se smazat server')
    } finally {
      setDeletingId(null)
    }
  }

  async function handleTest(id: string) {
    setTestingId(id)
    try {
      const result = await testMcpServer(id)
      setTestResults((prev) => ({ ...prev, [id]: result.tools }))
      setExpandedId(id)
      toast.success(`Připojeno — nalezeno ${result.tools_count} tools`)
    } catch {
      toast.error('Test selhal — server nedostupný nebo chybná konfigurace')
    } finally {
      setTestingId(null)
    }
  }

  return (
    <div className="flex flex-col gap-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-[var(--text-muted)]">
          Připoj externí MCP servery — jejich tools budou dostupné v chatu s prefixem{' '}
          <code className="text-[var(--text)]">{'<název>__<tool>'}</code>.
        </p>
        <Button size="sm" variant="secondary" onClick={() => setShowForm((v) => !v)}>
          <Plus size={14} />
          Přidat server
        </Button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="flex flex-col gap-3 p-4 rounded-lg border border-[var(--border)] bg-[var(--surface-2)]">
          <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
            Nový MCP server
          </span>
          <div className="flex flex-col gap-2">
            <input
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
              placeholder="Název (např. redmine)"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <input
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
              placeholder={
                form.transport_type === 'sse'
                  ? 'URL (např. http://mcp-redmine:8000/sse)'
                  : 'URL (např. https://mcp.example.com/mcp)'
              }
              value={form.url}
              onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
            />
            <input
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
              placeholder="Authorization header (volitelné, např. Bearer token123)"
              value={form.authHeader}
              onChange={(e) => setForm((f) => ({ ...f, authHeader: e.target.value }))}
            />
            <div className="flex items-center gap-3">
              <span className="text-xs text-[var(--text-muted)]">Transport:</span>
              <TransportSelect
                value={form.transport_type}
                onChange={(v) => setForm((f) => ({ ...f, transport_type: v }))}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={handleAdd} loading={saving}>
              Přidat
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setShowForm(false); setForm(EMPTY_FORM) }}>
              Zrušit
            </Button>
          </div>
        </div>
      )}

      {/* Server list */}
      {loadingList ? (
        <p className="text-sm text-[var(--text-muted)]">Načítám...</p>
      ) : servers.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">
          Žádné externí MCP servery. Přidej první server tlačítkem výše.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {servers.map((server) => (
            <div
              key={server.id}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] overflow-hidden"
            >
              {editingId === server.id ? (
                /* ── Inline edit form ── */
                <div className="flex flex-col gap-3 p-4">
                  <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    Upravit server
                  </span>
                  <div className="flex flex-col gap-2">
                    <input
                      className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
                      placeholder="Název"
                      value={editForm.name}
                      onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                    />
                    <input
                      className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
                      placeholder="URL"
                      value={editForm.url}
                      onChange={(e) => setEditForm((f) => ({ ...f, url: e.target.value }))}
                    />
                    <input
                      className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
                      placeholder="Authorization header (volitelné)"
                      value={editForm.authHeader}
                      onChange={(e) => setEditForm((f) => ({ ...f, authHeader: e.target.value }))}
                    />
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-[var(--text-muted)]">Transport:</span>
                      <TransportSelect
                        value={editForm.transport_type}
                        onChange={(v) => setEditForm((f) => ({ ...f, transport_type: v }))}
                      />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => handleSaveEdit(server)} loading={editSaving}>
                      <Check size={13} />
                      Uložit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={cancelEdit}>
                      <X size={13} />
                      Zrušit
                    </Button>
                  </div>
                </div>
              ) : (
                /* ── Server row ── */
                <div className="flex items-center gap-3 px-4 py-3">
                  {/* Enable/disable toggle */}
                  <button
                    onClick={() => handleToggle(server)}
                    disabled={togglingId === server.id}
                    className="shrink-0 text-[var(--text-muted)] hover:text-[var(--text)] transition-colors disabled:opacity-50"
                    title={server.enabled ? 'Deaktivovat' : 'Aktivovat'}
                  >
                    {server.enabled ? (
                      <ToggleRight size={20} className="text-[var(--accent)]" />
                    ) : (
                      <ToggleLeft size={20} />
                    )}
                  </button>

                  {/* Server info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[var(--text)] truncate">{server.name}</span>
                      <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)] shrink-0">
                        {server.transport_type === 'sse' ? 'SSE' : 'HTTP'}
                      </span>
                      {!server.enabled && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)]">
                          vypnuto
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-[var(--text-muted)] truncate block">{server.url}</span>
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleTest(server.id)}
                      loading={testingId === server.id}
                      title="Test připojení"
                    >
                      <PlugZap size={14} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => startEdit(server)}
                      title="Upravit"
                    >
                      <Pencil size={14} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setExpandedId(expandedId === server.id ? null : server.id)
                      }
                      title="Zobrazit tools"
                      disabled={!testResults[server.id]}
                    >
                      <ChevronRight
                        size={14}
                        className={`transition-transform ${expandedId === server.id ? 'rotate-90' : ''}`}
                      />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDelete(server.id)}
                      loading={deletingId === server.id}
                      title="Smazat"
                      className="text-red-400 hover:text-red-300"
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>
                </div>
              )}

              {/* Expanded tool list */}
              {expandedId === server.id && testResults[server.id] && editingId !== server.id && (
                <div className="border-t border-[var(--border)] px-4 py-3 flex flex-col gap-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-1">
                    Dostupné tools ({testResults[server.id].length})
                  </span>
                  {testResults[server.id].map((tool) => (
                    <div key={tool.name} className="flex items-start gap-3 text-sm">
                      <code className="shrink-0 px-1.5 py-0.5 rounded bg-[var(--bg)] border border-[var(--border)] text-xs text-[var(--accent)] font-mono">
                        {server.name}__{tool.name}
                      </code>
                      <span className="text-[var(--text-muted)] text-xs">{tool.description}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
