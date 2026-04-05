import { useState, useEffect } from 'react'
import { Plus, Pencil, Trash2, Check, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { listProjects, createProject, updateProject, deleteProject, type ProjectOut } from '../api/projects'

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectOut[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newInstructions, setNewInstructions] = useState('')
  const [editId, setEditId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editInstructions, setEditInstructions] = useState('')

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch(() => toast.error('Nepodařilo se načíst projekty'))
      .finally(() => setLoading(false))
  }, [])

  async function handleCreate() {
    if (!newName.trim()) return
    try {
      const proj = await createProject(newName.trim(), newInstructions.trim() || undefined)
      setProjects((prev) => [...prev, proj])
      setNewName('')
      setNewInstructions('')
      setCreating(false)
    } catch {
      toast.error('Nepodařilo se vytvořit projekt')
    }
  }

  async function handleUpdate(id: string) {
    try {
      const proj = await updateProject(id, {
        name: editName.trim() || undefined,
        instructions: editInstructions.trim() || null,
      })
      setProjects((prev) => prev.map((p) => (p.id === id ? proj : p)))
      setEditId(null)
    } catch {
      toast.error('Nepodařilo se uložit projekt')
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Opravdu smazat projekt? Konverzace budou přesunuty do globálních.')) return
    try {
      await deleteProject(id)
      setProjects((prev) => prev.filter((p) => p.id !== id))
    } catch {
      toast.error('Nepodařilo se smazat projekt')
    }
  }

  function startEdit(proj: ProjectOut) {
    setEditId(proj.id)
    setEditName(proj.name)
    setEditInstructions(proj.instructions ?? '')
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">Projekty</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            Každý projekt může mít vlastní instrukce (system prompt) pro AI asistenta.
          </p>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--accent)] text-white text-xs font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={13} />
          Nový projekt
        </button>
      </div>

      {/* Formulář pro nový projekt */}
      {creating && (
        <div className="border border-[var(--border)] rounded-xl p-4 flex flex-col gap-3 bg-[var(--surface-2)]">
          <input
            autoFocus
            type="text"
            placeholder="Název projektu"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors"
          />
          <textarea
            placeholder="Instrukce pro AI (system prompt) — volitelné"
            value={newInstructions}
            onChange={(e) => setNewInstructions(e.target.value)}
            rows={4}
            className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors resize-none font-mono"
          />
          <div className="flex gap-2 justify-end sticky bottom-0 bg-[var(--surface-2)] py-2 -mx-4 px-4 border-t border-[var(--border)] mt-1">
            <button
              onClick={() => { setCreating(false); setNewName(''); setNewInstructions('') }}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs text-[var(--text-muted)] hover:bg-[var(--surface)] transition-colors"
            >
              <X size={13} />
              Zrušit
            </button>
            <button
              onClick={handleCreate}
              disabled={!newName.trim()}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[var(--accent)] text-white text-xs font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
            >
              <Check size={13} />
              Vytvořit
            </button>
          </div>
        </div>
      )}

      {/* Seznam projektů */}
      {loading ? (
        <p className="text-sm text-[var(--text-muted)]">Načítám…</p>
      ) : projects.length === 0 && !creating ? (
        <p className="text-sm text-[var(--text-muted)]">Zatím žádné projekty. Klikni na "Nový projekt".</p>
      ) : (
        <div className="flex flex-col gap-3">
          {projects.map((proj) =>
            editId === proj.id ? (
              <div key={proj.id} className="border border-[var(--accent)]/40 rounded-xl p-4 flex flex-col gap-3 bg-[var(--surface-2)]">
                <input
                  autoFocus
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && !editInstructions && handleUpdate(proj.id)}
                  className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors"
                />
                <textarea
                  placeholder="Instrukce pro AI (system prompt) — volitelné"
                  value={editInstructions}
                  onChange={(e) => setEditInstructions(e.target.value)}
                  rows={6}
                  className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors resize-y font-mono"
                />
                <div className="flex gap-2 justify-end pt-1 sticky bottom-0 bg-[var(--surface-2)] py-2 -mx-4 px-4 border-t border-[var(--border)] mt-1">
                  <button
                    onClick={() => setEditId(null)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs text-[var(--text-muted)] hover:bg-[var(--surface)] transition-colors"
                  >
                    <X size={13} />
                    Zrušit
                  </button>
                  <button
                    onClick={() => handleUpdate(proj.id)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[var(--accent)] text-white text-xs font-medium hover:opacity-90 transition-opacity"
                  >
                    <Check size={13} />
                    Uložit
                  </button>
                </div>
              </div>
            ) : (
              <div key={proj.id} className="border border-[var(--border)] rounded-xl p-4 flex flex-col gap-2 bg-[var(--surface-2)] group">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-[var(--text)]">{proj.name}</span>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <button
                      onClick={() => startEdit(proj)}
                      title="Upravit"
                      className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-colors"
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      onClick={() => handleDelete(proj.id)}
                      title="Smazat"
                      className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--danger)]/10 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
                {proj.instructions ? (
                  <pre className="text-xs text-[var(--text-muted)] whitespace-pre-wrap font-mono bg-[var(--surface)] rounded-lg px-3 py-2 border border-[var(--border)] max-h-32 overflow-y-auto">
                    {proj.instructions}
                  </pre>
                ) : (
                  <p className="text-xs text-[var(--text-muted)] italic">Bez instrukcí</p>
                )}
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}
