import { useState, useEffect, useRef } from 'react'
import { Send, Plus, MessageSquare, Loader2, ChevronDown } from 'lucide-react'
import toast from 'react-hot-toast'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { fetchPreference, fetchProviders, savePreference, type ProviderInfo } from '../api/auth'
import {
  listConversations,
  getMessages,
  sendMessageStream,
  type ConversationOut,
  type MessageOut,
} from '../api/chat'

// ---------------------------------------------------------------------------
// Zpráva v UI (může být i streamovaná — role assistant s prázdným contentem)
// ---------------------------------------------------------------------------
interface UiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  model?: string | null
  streaming?: boolean
}

// ---------------------------------------------------------------------------
// Hlavní stránka
// ---------------------------------------------------------------------------
export function ChatPage() {
  const [conversations, setConversations] = useState<ConversationOut[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [provider, setProvider] = useState('together')
  const [model, setModel] = useState('meta-llama/Llama-3.3-70B-Instruct-Turbo')
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [modelPickerOpen, setModelPickerOpen] = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pickerRef = useRef<HTMLDivElement>(null)

  // Načtení konverzací a preference modelu
  useEffect(() => {
    listConversations().then(setConversations).catch(() => {})
    Promise.all([fetchPreference(), fetchProviders()])
      .then(([pref, providerList]) => {
        setProvider(pref.provider)
        setModel(pref.model)
        setProviders(providerList)
      })
      .catch(() => {})
  }, [])

  // Zavřít picker kliknutím mimo
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setModelPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Scroll na konec při nových zprávách
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function openConversation(convId: string) {
    setActiveConvId(convId)
    try {
      const msgs = await getMessages(convId)
      setMessages(msgs.map((m: MessageOut) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        model: m.model,
      })))
    } catch {
      toast.error('Nepodařilo se načíst zprávy')
    }
  }

  function newConversation() {
    setActiveConvId(null)
    setMessages([])
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || sending) return

    setInput('')
    setSending(true)

    // Optimisticky přidej uživatelovu zprávu
    const tempUserId = crypto.randomUUID()
    const tempBotId = crypto.randomUUID()
    setMessages((prev) => [
      ...prev,
      { id: tempUserId, role: 'user', content: text },
      { id: tempBotId, role: 'assistant', content: '', model, streaming: true },
    ])

    try {
      await sendMessageStream({
        conversationId: activeConvId,
        message: text,
        provider,
        model,
        onChunk: (chunk) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempBotId ? { ...m, content: m.content + chunk } : m
            )
          )
        },
        onDone: (convId) => {
          const finalConvId = convId || activeConvId
          // Nahraď streamed content čistými daty z DB
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
                  }))
                )
              )
              .catch(() => {
                // Fallback — aspoň ukonči streaming flag
                setMessages((prev) =>
                  prev.map((m) => (m.id === tempBotId ? { ...m, streaming: false } : m))
                )
              })
          } else {
            setMessages((prev) =>
              prev.map((m) => (m.id === tempBotId ? { ...m, streaming: false } : m))
            )
          }
          // Pokud to byla nová konverzace, přidej ji do listu
          if (!activeConvId && convId) {
            setActiveConvId(convId)
            listConversations().then(setConversations).catch(() => {})
          }
          setSending(false)
        },
      })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Chyba při odesílání'
      toast.error(msg)
      // Odstraň prázdnou bot zprávu
      setMessages((prev) => prev.filter((m) => m.id !== tempBotId))
      setSending(false)
    }
  }

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

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sidebar s konverzacemi */}
      <aside className="w-56 shrink-0 flex flex-col border-r border-[var(--border)] bg-[var(--surface)]">
        <div className="p-3 border-b border-[var(--border)]">
          <button
            onClick={newConversation}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
          >
            <Plus size={15} />
            Nová konverzace
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 flex flex-col gap-0.5">
          {conversations.length === 0 && (
            <p className="text-xs text-[var(--text-muted)] px-3 py-2">Žádné konverzace</p>
          )}
          {conversations.map((conv) => (
            <button
              key={conv.id}
              onClick={() => openConversation(conv.id)}
              className={[
                'w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors',
                conv.id === activeConvId
                  ? 'bg-[var(--accent)]/15 text-[var(--text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]',
              ].join(' ')}
            >
              {conv.title}
            </button>
          ))}
        </nav>
      </aside>

      {/* Hlavní chat oblast */}
      <div className="flex-1 flex flex-col min-w-0">
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
                    {msg.streaming && !msg.content && <Loader2 size={14} className="animate-spin inline-block" />}
                    {msg.streaming && msg.content && <span className="inline-block w-1.5 h-3.5 bg-current ml-0.5 align-middle animate-pulse rounded-sm" />}
                  </>
                )}
              </div>
              {msg.role === 'assistant' && msg.model && (
                <span className="text-[10px] text-[var(--text-muted)] mt-0.5 px-1">
                  {providers.flatMap(p => p.models).find(m => m.model === msg.model)?.label ?? msg.model.split('/').pop()}
                </span>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-4 py-3 border-t border-[var(--border)] bg-[var(--surface)]">
          <div className="flex items-end gap-2 max-w-3xl mx-auto">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder="Napiš zprávu… (Enter odešle, Shift+Enter nový řádek)"
              rows={1}
              disabled={sending}
              className={[
                'flex-1 resize-none rounded-xl bg-[var(--surface-2)] border border-[var(--border)]',
                'focus:border-[var(--accent)] outline-none px-4 py-2.5 text-sm text-[var(--text)]',
                'placeholder:text-[var(--text-muted)] transition-colors leading-relaxed',
                'disabled:opacity-50 min-h-[40px] max-h-[160px] overflow-y-auto',
                '[field-sizing:content]',
              ].join(' ')}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className={[
                'p-2.5 rounded-xl transition-colors shrink-0',
                input.trim() && !sending
                  ? 'bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white'
                  : 'bg-[var(--surface-2)] text-[var(--text-muted)] cursor-not-allowed',
              ].join(' ')}
            >
              {sending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
          <div className="flex justify-center mt-1.5 max-w-3xl mx-auto relative" ref={pickerRef}>
            <button
              onClick={() => setModelPickerOpen((o) => !o)}
              className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors px-2 py-0.5 rounded-md hover:bg-[var(--surface-2)]"
            >
              <span>{provider} · {model}</span>
              <ChevronDown size={12} className={modelPickerOpen ? 'rotate-180' : ''} style={{ transition: 'transform 0.15s' }} />
            </button>

            {modelPickerOpen && (
              <div
                onMouseDown={(e) => e.stopPropagation()}
                className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 w-80 max-h-72 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-xl z-50"
              >
                {providers.map((p) => (
                  <div key={p.id}>
                    <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                      {p.id}
                    </div>
                    {p.models.map((m) => (
                      <button
                        key={m.model}
                        onClick={() => handleModelSelect(m.provider, m.model)}
                        className={[
                          'w-full text-left px-3 py-2 text-xs transition-colors truncate',
                          m.provider === provider && m.model === model
                            ? 'bg-[var(--accent)]/15 text-[var(--text)]'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]',
                        ].join(' ')}
                      >
                        {m.label}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
