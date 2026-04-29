import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ChevronLeft, Save, Undo2, LayoutTemplate, ChevronDown } from 'lucide-react'
import toast from 'react-hot-toast'
import MDEditor from '@uiw/react-md-editor'
import rehypeSanitize from 'rehype-sanitize'

import { fetchPreference, savePreference, fetchProviders, type ProviderInfo } from '../api/auth'
import { documentsApi, generateDocumentStream, type DocumentOut } from '../api/documents'
import { ChatInput } from '../components/chat/ChatInput'

export function DocumentEditorPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  
  const [doc, setDoc] = useState<DocumentOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)

  const [title, setTitle] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [content, setContent] = useState('')

  // Historie pro Undo
  const [history, setHistory] = useState<string[]>([])
  
  // Auto-save debounce timeout
  const saveTimeoutRef = useRef<number | null>(null)

  // Model a provider
  const [provider, setProvider] = useState('together')
  const [model, setModel] = useState('meta-llama/Llama-3.3-70B-Instruct-Turbo')
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [modelPickerOpen, setModelPickerOpen] = useState(false)
  const pickerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    Promise.all([fetchPreference(), fetchProviders()])
      .then(([pref, providerList]) => {
        setProvider(pref.provider)
        setModel(pref.model)
        setProviders(providerList)
      })
      .catch(() => toast.error('Nepodařilo se načíst modely'))
  }, [])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setModelPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  async function handleModelSelect(providerName: string, modelName: string) {
    setProvider(providerName)
    setModel(modelName)
    setModelPickerOpen(false)
    try {
      await savePreference(providerName, modelName)
    } catch {
      toast.error('Nepodařilo se uložit výběr modelu')
    }
  }

  useEffect(() => {
    if (!id) return
    documentsApi.get(id)
      .then(d => {
        setDoc(d)
        setTitle(d.title)
        setSourceText(d.source_text)
        setContent(d.content)
      })
      .catch(() => {
        toast.error('Nepodařilo se načíst dokument')
        navigate('/documents')
      })
      .finally(() => setLoading(false))
  }, [id, navigate])

  const saveDocument = useCallback(async (overrides?: Partial<DocumentOut>) => {
    if (!id) return
    setSaving(true)
    try {
      const payload = {
        title: overrides?.title ?? title,
        source_text: overrides?.source_text ?? sourceText,
        content: overrides?.content ?? content
      }
      await documentsApi.update(id, payload)
    } catch {
      toast.error('Nepodařilo se uložit dokument')
    } finally {
      setSaving(false)
    }
  }, [id, title, sourceText, content])

  // Debounced auto-save (pro levý a pravý panel)
  useEffect(() => {
    if (loading || !doc) return
    if (title === doc.title && sourceText === doc.source_text && content === doc.content) return

    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(() => {
      saveDocument()
      setDoc(prev => prev ? { ...prev, title, source_text: sourceText, content } : null)
    }, 1500)

    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    }
  }, [title, sourceText, content, doc, loading, saveDocument])

  async function handleGenerate(prompt: string) {
    if (!id || !model) return
    
    // Uložíme aktuální stav před změnou do historie
    setHistory(prev => [...prev, content].slice(-10)) // držet max 10 kroků
    
    setGenerating(true)
    let newContent = ''

    await generateDocumentStream(
      id,
      {
        prompt,
        model,
        provider,
      },
      (delta) => {
        newContent += delta
        setContent(newContent)
      },
      (err) => {
        toast.error('Chyba při generování: ' + err)
        setGenerating(false)
      },
      () => {
        setGenerating(false)
        // Uložení se postará auto-save
      }
    )
  }

  function handleUndo() {
    if (history.length === 0) return
    const prevContent = history[history.length - 1]
    setContent(prevContent)
    setHistory(prev => prev.slice(0, -1))
    toast.success('Krok vrácen')
  }

  if (loading) return <div className="p-8 text-[var(--text-muted)] text-sm">Načítání dokumentu...</div>
  if (!doc) return null

  return (
    <div className="flex flex-col h-full bg-[var(--surface-2)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[var(--surface)] border-b border-[var(--border)] shrink-0 z-10">
        <div className="flex items-center gap-3">
          <button 
            onClick={() => navigate('/documents')}
            className="p-1.5 hover:bg-[var(--surface-2)] rounded-lg text-[var(--text-muted)] transition-colors"
          >
            <ChevronLeft size={18} />
          </button>
          <div className="w-px h-4 bg-[var(--border)]" />
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            className="bg-transparent border-none outline-none font-semibold text-lg max-w-[300px] text-[var(--text)] focus:ring-1 focus:ring-[var(--accent)] rounded px-2 py-0.5"
            placeholder="Název dokumentu"
          />
        </div>
        
        <div className="flex items-center gap-4 text-xs relative">
          <div className="relative" ref={pickerRef}>
            <button
              onClick={() => setModelPickerOpen(o => !o)}
              className="flex items-center gap-1.5 text-[var(--text-muted)] hover:text-[var(--text)] transition-colors px-2 py-1 rounded-md hover:bg-[var(--surface-2)]"
            >
              <LayoutTemplate size={14} />
              <span>{model.split('/').pop()}</span>
              <ChevronDown size={12} className={modelPickerOpen ? 'rotate-180' : ''} style={{ transition: 'transform 0.15s' }} />
            </button>

            {modelPickerOpen && (
              <div className="absolute right-0 top-full mt-2 w-64 max-h-[300px] overflow-y-auto bg-[var(--surface)] border border-[var(--border)] rounded-xl shadow-xl z-50">
                {providers.map((p) => (
                  <div key={p.id}>
                    <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] bg-[var(--surface-2)]">
                      {p.id}
                    </div>
                    {p.models.map((m) => (
                      <button
                        key={m.model}
                        onClick={() => handleModelSelect(m.provider, m.model)}
                        className={[
                          'w-full text-left px-3 py-2 text-xs transition-colors truncate flex items-center justify-between gap-2',
                          m.provider === provider && m.model === model
                            ? 'bg-[var(--accent)]/15 text-[var(--text)]'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]',
                        ].join(' ')}
                      >
                        <span className="truncate">{m.label}</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
          
          <div className={`flex items-center gap-1.5 ${saving ? 'text-[var(--text-muted)]' : 'text-green-500'}`}>
            <Save size={14} />
            {saving ? 'Ukládám...' : 'Uloženo'}
          </div>
        </div>
      </div>

      {/* Hlavní obsah - dva panely vedle sebe */}
      <div className="flex-1 flex overflow-hidden p-4 gap-4 z-0">
        {/* Východisko */}
        <div className="flex-1 flex flex-col bg-[var(--surface)] border border-[var(--border)] rounded-xl overflow-hidden shadow-sm">
          <div className="px-4 py-2 border-b border-[var(--border)] bg-[var(--surface-2)] text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Východisko (Podklady)
          </div>
          <textarea
            value={sourceText}
            onChange={e => setSourceText(e.target.value)}
            placeholder="Zde vložte zdrojová data, podklady, osnovu nebo požadavky pro výsledný článek..."
            className="flex-1 p-4 bg-transparent outline-none resize-none text-sm leading-relaxed"
          />
        </div>

        {/* Výsledek */}
        <div className="flex-1 flex flex-col bg-[var(--surface)] border border-[var(--border)] rounded-xl overflow-hidden shadow-sm relative">
          <div className="px-4 py-2 border-b border-[var(--border)] bg-[var(--surface-2)] flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Výsledek
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={handleUndo}
                disabled={history.length === 0 || generating}
                className="flex items-center gap-1.5 text-[10px] uppercase font-semibold text-[var(--text-muted)] hover:text-[var(--text)] disabled:opacity-50 disabled:hover:text-[var(--text-muted)] transition-colors"
              >
                <Undo2 size={12} />
                Zpět
              </button>
            </div>
          </div>
          <div
            data-color-mode="light"
            className={`flex-1 overflow-hidden transition-opacity ${generating ? 'opacity-60 pointer-events-none' : ''}`}
          >
            <MDEditor
              value={content}
              onChange={(val) => setContent(val || '')}
              height="100%"
              preview="live"
              hideToolbar={false}
              previewOptions={{
                rehypePlugins: [[rehypeSanitize]],
              }}
              style={{ borderRadius: 0, border: 'none', background: '#ffffff', boxShadow: 'none', color: '#111' }}
            />
          </div>
        </div>
      </div>

      {/* Dolní panel (Chat) */}
      <div className="p-4 bg-[var(--surface)] border-t border-[var(--border)] shrink-0">
        <div className="max-w-4xl mx-auto">
          <ChatInput
            onSend={(text) => handleGenerate(text)}
            disabled={generating}
            webSearch={false}
            onWebSearchToggle={() => {}}
            overridden={false}
            placeholder="Zadejte pokyn pro úpravu Výsledku (např. 'Zkrať druhý odstavec a přidej odrážky')..."
          />
        </div>
      </div>
    </div>
  )
}