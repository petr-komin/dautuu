import { useState, useEffect, useRef } from 'react'
import { useSearchParams, useNavigate, useOutletContext } from 'react-router-dom'
import { MessageSquare, Loader2, ChevronDown, Globe, FileText, FolderOpen, FilePlus, Trash2, X, Search, ExternalLink, Sliders, Sparkles, Mail, Brain } from 'lucide-react'
import toast from 'react-hot-toast'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { fetchPreference, fetchProviders, savePreference, type ProviderInfo } from '../api/auth'
import {
  getMessages,
  sendMessageStream,
  type MessageOut,
  type ToolEvent,
  type RoutingEvent,
} from '../api/chat'
import { listProjects } from '../api/projects'
import { ChatInput } from '../components/chat/ChatInput'

const WEB_SEARCH_STORAGE_KEY = 'dautuu:webSearch'

interface OutletCtx {
  onConversationCreated: () => void
}

function toolEventLabel(event: ToolEvent): string {
  if (event.type === 'search') return `Hledám: ${event.query}`
  const labels: Record<string, string> = {
    read_file: 'Čtu soubor',
    write_file: 'Zapisuji soubor',
    list_files: 'Procházím adresář',
    create_directory: 'Vytvářím adresář',
    delete_file: 'Mažu soubor',
  }
  const label = labels[event.name] ?? event.name
  return event.path ? `${label}: ${event.path}` : label
}

function toolEventIcon(event: ToolEvent) {
  if (event.type === 'search') return <Globe size={12} className="shrink-0" />
  const icons: Record<string, React.ReactNode> = {
    read_file: <FileText size={12} className="shrink-0" />,
    write_file: <FilePlus size={12} className="shrink-0" />,
    list_files: <FolderOpen size={12} className="shrink-0" />,
    create_directory: <FolderOpen size={12} className="shrink-0" />,
    delete_file: <Trash2 size={12} className="shrink-0" />,
  }
  return icons[event.name] ?? <FileText size={12} className="shrink-0" />
}

interface UiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  model?: string | null
  streaming?: boolean
  activeToolEvent?: ToolEvent | null
  citations?: string[]
  numSourcesUsed?: number
  routing?: RoutingEvent
}

export function ChatPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { onConversationCreated } = useOutletContext<OutletCtx>()

  const activeConvId = searchParams.get('conv')
  const projectId = searchParams.get('project')

  const [messages, setMessages] = useState<UiMessage[]>([])
  const [sending, setSending] = useState(false)
  const [provider, setProvider] = useState('together')
  const [model, setModel] = useState('meta-llama/Llama-3.3-70B-Instruct-Turbo')
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [modelPickerOpen, setModelPickerOpen] = useState(false)
  const [projectName, setProjectName] = useState<string | null>(null)
  const [webSearch, setWebSearch] = useState<boolean>(() => {
    const stored = localStorage.getItem(WEB_SEARCH_STORAGE_KEY)
    return stored === null ? true : stored === 'true'
  })
  const [grokSearch, setGrokSearch] = useState(false)
  const [grokReasoningEffort, setGrokReasoningEffort] = useState<'low' | 'high' | null>('low')
  const [showAdvancedModels, setShowAdvancedModels] = useState(false)
  const [autoMode, setAutoMode] = useState<boolean>(() => {
    const stored = localStorage.getItem('dautuu:autoMode')
    // Default = ZAPNUTO. Vypnout musí uživatel explicitně.
    return stored === null ? true : stored === '1'
  })
  const [webSearchBackend, setWebSearchBackend] = useState<'tavily' | 'grok'>(() => {
    const stored = localStorage.getItem('dautuu:webSearchBackend')
    return stored === 'grok' ? 'grok' : 'tavily'
  })

  const bottomRef = useRef<HTMLDivElement>(null)
  const pickerRef = useRef<HTMLDivElement>(null)

  // Načti model preference
  useEffect(() => {
    Promise.all([fetchPreference(), fetchProviders()])
      .then(([pref, providerList]) => {
        setProvider(pref.provider)
        setModel(pref.model)
        setProviders(providerList)
      })
      .catch(() => {})
  }, [])

  // Načti název projektu pro indikátor
  useEffect(() => {
    if (!projectId || activeConvId) {
      setProjectName(null)
      return
    }
    listProjects().then((projs) => {
      const proj = projs.find((p) => p.id === projectId)
      setProjectName(proj?.name ?? null)
    }).catch(() => {})
  }, [projectId, activeConvId])

  // Načti zprávy při změně konverzace
  useEffect(() => {
    if (!activeConvId) {
      setMessages([])
      return
    }
    getMessages(activeConvId)
      .then((msgs) =>
        setMessages(
          msgs.map((m: MessageOut) => ({
            id: m.id,
            role: m.role as 'user' | 'assistant',
            content: m.content,
            model: m.model,
          }))
        )
      )
      .catch(() => toast.error('Nepodařilo se načíst zprávy'))
  }, [activeConvId])

  useEffect(() => {
    localStorage.setItem(WEB_SEARCH_STORAGE_KEY, String(webSearch))
  }, [webSearch])

  useEffect(() => {
    localStorage.setItem('dautuu:autoMode', autoMode ? '1' : '0')
  }, [autoMode])

  useEffect(() => {
    localStorage.setItem('dautuu:webSearchBackend', webSearchBackend)
  }, [webSearchBackend])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setModelPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend(text: string) {
    setSending(true)

    const tempUserId = crypto.randomUUID()
    const tempBotId = crypto.randomUUID()
    setMessages((prev) => [
      ...prev,
      { id: tempUserId, role: 'user', content: text },
      { id: tempBotId, role: 'assistant', content: '', model, streaming: true, activeToolEvent: null },
    ])

    try {
      await sendMessageStream({
        conversationId: activeConvId,
        message: text,
        provider,
        model,
        webSearch,
        webSearchBackend,
        grokSearch: { enabled: grokSearch, mode: 'auto' },
        grokReasoningEffort: provider === 'xai' ? grokReasoningEffort : null,
        routingMode: autoMode ? 'auto' : 'manual',
        projectId: projectId,
        onToolEvent: (event) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempBotId ? { ...m, activeToolEvent: event } : m
            )
          )
        },
        onRouting: (ev) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === tempBotId ? { ...m, routing: ev } : m))
          )
        },
        onCitations: (ev) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempBotId
                ? { ...m, citations: ev.citations, numSourcesUsed: ev.num_sources_used }
                : m
            )
          )
        },
        onChunk: (chunk) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempBotId
                ? { ...m, content: m.content + chunk, activeToolEvent: null }
                : m
            )
          )
        },
        onDone: (convId) => {
          const finalConvId = convId || activeConvId
          if (finalConvId) {
            getMessages(finalConvId)
              .then((msgs) =>
                setMessages(
                  msgs.map((m: MessageOut) => ({
                    id: m.id,
                    role: m.role as 'user' | 'assistant',
                    content: m.content,
                    model: m.model,
                    streaming: false,
                    activeToolEvent: null,
                    citations: m.tool_data?.citations,
                    numSourcesUsed: m.tool_data?.num_sources_used,
                  }))
                )
              )
              .catch(() => {
                setMessages((prev) =>
                  prev.map((m) => (m.id === tempBotId ? { ...m, streaming: false, activeToolEvent: null } : m))
                )
              })
          } else {
            setMessages((prev) =>
              prev.map((m) => (m.id === tempBotId ? { ...m, streaming: false, activeToolEvent: null } : m))
            )
          }
          // Pokud to byla nová konverzace → naviguj na ni a refreshni sidebar
          if (!activeConvId && convId) {
            navigate(`/chat?conv=${convId}`, { replace: true })
            onConversationCreated()
          }
          setSending(false)
        },
      })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Chyba při odesílání'
      toast.error(msg)
      setMessages((prev) => prev.filter((m) => m.id !== tempBotId))
      setSending(false)
    }
  }

  async function handleModelSelect(providerName: string, modelName: string) {
    setProvider(providerName)
    setModel(modelName)
    setModelPickerOpen(false)
    // Reset Grok Search při přepnutí na jiného providera
    if (providerName !== 'xai') {
      setGrokSearch(false)
    }
    try {
      await savePreference(providerName, modelName)
    } catch {
      toast.error('Nepodařilo se uložit výběr modelu')
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Zprávy */}
      <div className="flex-1 overflow-y-auto px-4 py-6 flex flex-col gap-4">
        {messages.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center text-[var(--text-muted)] gap-3 select-none">
            <MessageSquare size={36} strokeWidth={1.5} />
            <p className="text-sm">Začni psát zprávu níže</p>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={['flex flex-col', msg.role === 'user' ? 'items-end' : 'items-start'].join(' ')}
          >
            {msg.role === 'assistant' && msg.routing && (
              <div
                className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] mb-1 px-1"
                title={msg.routing.reasoning + (msg.routing.fallback ? ' (fallback)' : ` · ${msg.routing.took_ms}ms`)}
              >
                <Sparkles size={10} className="text-[var(--accent)]/70" />
                <span>Auto:</span>
                {msg.routing.web && (
                  <span className="flex items-center gap-0.5 px-1 rounded bg-[var(--accent)]/10 text-[var(--accent)]">
                    <Globe size={9} /> web
                  </span>
                )}
                {msg.routing.history && (
                  <span className="flex items-center gap-0.5 px-1 rounded bg-[var(--surface-2)]">
                    <Brain size={9} /> history
                  </span>
                )}
                {msg.routing.email && (
                  <span className="flex items-center gap-0.5 px-1 rounded bg-[var(--surface-2)]">
                    <Mail size={9} /> email
                  </span>
                )}
                {!msg.routing.web && !msg.routing.history && !msg.routing.email && (
                  <span className="opacity-60">jen znalosti modelu</span>
                )}
              </div>
            )}
            {msg.role === 'assistant' && msg.activeToolEvent && (
              <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] mb-1.5 px-1 animate-pulse">
                {toolEventIcon(msg.activeToolEvent)}
                <span>{toolEventLabel(msg.activeToolEvent)}</span>
              </div>
            )}
            <div
              className={[
                'max-w-[75%] rounded-2xl px-4 py-2.5 text-sm break-words',
                msg.role === 'user'
                  ? 'bg-[var(--user-bubble)] text-[var(--user-bubble-text)] rounded-br-sm whitespace-pre-wrap'
                  : 'bg-[var(--surface-2)] text-[var(--text)] rounded-bl-sm prose-chat',
              ].join(' ')}
            >
              {msg.role === 'user' ? (
                msg.content
              ) : (
                <>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content || '\u200b'}
                  </ReactMarkdown>
                  {msg.streaming && !msg.content && !msg.activeToolEvent && (
                    <Loader2 size={14} className="animate-spin inline-block" />
                  )}
                  {msg.streaming && msg.content && (
                    <span className="inline-block w-1.5 h-3.5 bg-current ml-0.5 align-middle animate-pulse rounded-sm" />
                  )}
                </>
              )}
            </div>
            {msg.role === 'assistant' && msg.citations && msg.citations.length > 0 && (
              <div className="max-w-[75%] mt-1.5 flex flex-col gap-1 px-1">
                <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-semibold">
                  <Globe size={10} />
                  <span>Zdroje{msg.numSourcesUsed ? ` (${msg.numSourcesUsed})` : ''}</span>
                </div>
                <div className="flex flex-col gap-0.5">
                  {msg.citations.map((url, idx) => {
                    let host = url
                    try { host = new URL(url).hostname.replace(/^www\./, '') } catch { /* keep raw */ }
                    return (
                      <a
                        key={`${msg.id}-cit-${idx}`}
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors truncate"
                        title={url}
                      >
                        <span className="text-[10px] text-[var(--text-muted)]/60 w-4 shrink-0 text-right">{idx + 1}.</span>
                        <ExternalLink size={10} className="shrink-0" />
                        <span className="truncate">{host}</span>
                      </a>
                    )
                  })}
                </div>
              </div>
            )}
            {msg.role === 'assistant' && msg.model && (
              <span className="text-[10px] text-[var(--text-muted)] mt-0.5 px-1">
                {providers.flatMap(p => p.models).find(m => m.model === msg.model)?.label ?? msg.model.split('/').pop()}
              </span>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <ChatInput
        onSend={handleSend}
        disabled={sending}
        webSearch={webSearch}
        onWebSearchToggle={() => setWebSearch((v) => !v)}
        overridden={autoMode}
      />

      {/* Indikátor kontextu nové konverzace */}
      {!activeConvId && (
        <div className="flex items-center justify-center gap-2 py-1.5 border-t border-[var(--border)] bg-[var(--surface)]">
          {projectId && projectName ? (
            <div className="flex items-center gap-1.5 text-xs text-[var(--accent)] bg-[var(--accent)]/10 border border-[var(--accent)]/25 rounded-full px-3 py-0.5">
              <FolderOpen size={11} />
              <span>Nová konverzace v projektu <strong>{projectName}</strong></span>
              <button
                onClick={() => navigate('/chat')}
                className="ml-1 text-[var(--accent)]/60 hover:text-[var(--accent)] transition-colors"
                title="Zrušit — přejít do globálních"
              >
                <X size={11} />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
              <MessageSquare size={11} />
              <span>Nová globální konverzace</span>
            </div>
          )}
        </div>
      )}

      {/* Model picker */}
      <div className="flex justify-center items-center gap-2 py-1.5 bg-[var(--surface)] border-t border-[var(--border)] relative" ref={pickerRef}>
        <button
          onClick={() => setModelPickerOpen((o) => !o)}
          className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors px-2 py-0.5 rounded-md hover:bg-[var(--surface-2)]"
        >
          <span>{provider} · {model}</span>
          <ChevronDown size={12} className={modelPickerOpen ? 'rotate-180' : ''} style={{ transition: 'transform 0.15s' }} />
        </button>

        {/* Auto routing toggle — klasifikátor rozhodne kam pro kontext */}
        <button
          onClick={() => setAutoMode((v) => !v)}
          title="Auto: rychlý LLM rozhodne jestli hledat na webu / v historii / v emailech"
          className={[
            'flex items-center gap-1 text-xs px-2 py-0.5 rounded-md transition-colors',
            autoMode
              ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30'
              : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]',
          ].join(' ')}
        >
          <Sparkles size={12} />
          <span>Auto</span>
        </button>

        {/* Web search backend — Tavily vs Grok Live Search.
            Skrýt pro xAI providera (ten používá své search_parameters). */}
        {provider !== 'xai' && webSearch && (
          <button
            onClick={() => setWebSearchBackend((b) => (b === 'tavily' ? 'grok' : 'tavily'))}
            title={
              webSearchBackend === 'grok'
                ? 'Web search: Grok Live Search (xAI). Klikni pro Tavily.'
                : 'Web search: Tavily. Klikni pro Grok Live Search.'
            }
            className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-md transition-colors text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)] border border-[var(--border)]"
          >
            <Search size={12} />
            <span>{webSearchBackend === 'grok' ? 'Grok' : 'Tavily'}</span>
          </button>
        )}

        {/* Grok Live Search toggle — viditelný jen pro xAI provider */}
        {provider === 'xai' && !autoMode && (
          <button
            onClick={() => setGrokSearch((g) => !g)}
            title="Grok Live Search (web + X/Twitter)"
            className={[
              'flex items-center gap-1 text-xs px-2 py-0.5 rounded-md transition-colors',
              grokSearch
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30'
                : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]',
            ].join(' ')}
          >
            <Search size={12} />
            <span>Search</span>
          </button>
        )}

        {/* Reasoning effort selector — jen pro xAI modely co to podporují */}
        {provider === 'xai' && providers.flatMap(p => p.models).find(m => m.model === model)?.supports_reasoning_effort && (
          <div className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-md text-[var(--text-muted)] bg-[var(--surface-2)]/60">
            <Sliders size={12} />
            <span>Effort:</span>
            {(['low', 'high'] as const).map((lvl) => (
              <button
                key={lvl}
                onClick={() => setGrokReasoningEffort(lvl)}
                className={[
                  'px-1.5 rounded transition-colors',
                  grokReasoningEffort === lvl
                    ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                    : 'hover:text-[var(--text)]',
                ].join(' ')}
              >
                {lvl}
              </button>
            ))}
          </div>
        )}

        {modelPickerOpen && (
          <div
            onMouseDown={(e) => e.stopPropagation()}
            className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 w-80 max-h-72 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-xl z-50"
          >
            {providers.map((p) => {
              const visibleModels = p.models.filter(m => showAdvancedModels || (m.tier ?? 'basic') === 'basic')
              if (visibleModels.length === 0 && !showAdvancedModels) return null
              return (
                <div key={p.id}>
                  <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                    {p.id}
                  </div>
                  {visibleModels.map((m) => (
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
                      <span className="flex items-center gap-1 shrink-0">
                        {m.slow && <span className="text-[9px] text-amber-500/80" title="Reasoning model — pomalejší TTFT">slow</span>}
                        {(m.tier ?? 'basic') === 'advanced' && <span className="text-[9px] text-[var(--text-muted)]/60">adv</span>}
                      </span>
                    </button>
                  ))}
                </div>
              )
            })}
            <button
              onClick={() => setShowAdvancedModels((v) => !v)}
              className="w-full text-left px-3 py-2 text-[10px] uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] border-t border-[var(--border)] transition-colors"
            >
              {showAdvancedModels ? '− Skrýt advanced modely' : '+ Zobrazit advanced modely'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
