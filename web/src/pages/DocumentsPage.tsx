import { useState, useEffect } from 'react'
import { Plus, Trash2, FileText } from 'lucide-react'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'
import { documentsApi, type DocumentOut } from '../api/documents'

export function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    documentsApi.list()
      .then(setDocuments)
      .catch(() => toast.error('Nepodařilo se načíst dokumenty'))
      .finally(() => setLoading(false))
  }, [])

  async function handleCreate() {
    try {
      const doc = await documentsApi.create({
        title: 'Nový dokument',
        content: '',
        source_text: ''
      })
      navigate(`/documents/${doc.id}`)
    } catch {
      toast.error('Nepodařilo se vytvořit dokument')
    }
  }

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm('Opravdu chcete smazat tento dokument?')) return
    try {
      await documentsApi.delete(id)
      setDocuments(prev => prev.filter(d => d.id !== id))
      toast.success('Dokument smazán')
    } catch {
      toast.error('Nepodařilo se smazat dokument')
    }
  }

  if (loading) {
    return <div className="p-8 text-[var(--text-muted)] text-sm">Načítání...</div>
  }

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <FileText className="text-[var(--accent)]" />
          Dokumenty
        </h1>
        <button
          onClick={handleCreate}
          className="flex items-center gap-2 px-3 py-1.5 bg-[var(--accent)] text-white text-sm font-medium rounded hover:opacity-90 transition-opacity"
        >
          <Plus size={16} />
          Nový dokument
        </button>
      </div>

      {documents.length === 0 ? (
        <div className="p-8 text-center text-[var(--text-muted)] border border-dashed border-[var(--border)] rounded-xl">
          Zatím nemáte žádné dokumenty.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {documents.map((doc) => (
            <div
              key={doc.id}
              onClick={() => navigate(`/documents/${doc.id}`)}
              className="group bg-[var(--surface-2)] border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:border-[var(--accent)] transition-colors relative flex flex-col"
            >
              <div className="flex items-start justify-between mb-2">
                <h3 className="font-semibold text-sm truncate pr-6" title={doc.title}>
                  {doc.title}
                </h3>
                <button
                  onClick={(e) => handleDelete(doc.id, e)}
                  className="absolute top-3 right-3 p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--danger)]/10 opacity-0 group-hover:opacity-100 transition-all"
                  title="Smazat dokument"
                >
                  <Trash2 size={14} />
                </button>
              </div>
              <p className="text-xs text-[var(--text-muted)] line-clamp-3 flex-1 mb-3">
                {doc.content.slice(0, 150) || doc.source_text.slice(0, 150) || 'Prázdný dokument'}
              </p>
              <div className="text-[10px] text-[var(--text-muted)] mt-auto pt-2 border-t border-[var(--border)]">
                Upraveno: {new Date(doc.updated_at).toLocaleString('cs-CZ')}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}