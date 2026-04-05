import { useState } from 'react'
import { Send, Globe, GlobeOff, Loader2 } from 'lucide-react'

interface ChatInputProps {
  onSend: (text: string) => void
  disabled: boolean
  webSearch: boolean
  onWebSearchToggle: () => void
}

export function ChatInput({ onSend, disabled, webSearch, onWebSearchToggle }: ChatInputProps) {
  const [input, setInput] = useState('')

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    const text = input.trim()
    if (!text || disabled) return
    setInput('')
    onSend(text)
  }

  return (
    <div className="px-4 py-3 border-t border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <button
          onClick={onWebSearchToggle}
          title={webSearch ? 'Web search zapnut — klikni pro vypnutí' : 'Web search vypnut — klikni pro zapnutí'}
          className={[
            'p-2.5 rounded-xl transition-colors shrink-0',
            webSearch
              ? 'text-[var(--accent)] hover:bg-[var(--surface-2)]'
              : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)]',
          ].join(' ')}
        >
          {webSearch ? <Globe size={18} /> : <GlobeOff size={18} />}
        </button>

        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Napiš zprávu… (Enter odešle, Shift+Enter nový řádek)"
          rows={1}
          disabled={disabled}
          className={[
            'flex-1 resize-none rounded-xl bg-[var(--surface-2)] border border-[var(--border)]',
            'focus:border-[var(--accent)] outline-none px-4 py-2.5 text-sm text-[var(--text)]',
            'placeholder:text-[var(--text-muted)] transition-colors leading-relaxed',
            'disabled:opacity-50 min-h-[40px] max-h-[160px] overflow-y-auto',
            '[field-sizing:content]',
          ].join(' ')}
        />

        <button
          onClick={submit}
          disabled={!input.trim() || disabled}
          className={[
            'p-2.5 rounded-xl transition-colors shrink-0',
            input.trim() && !disabled
              ? 'bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white'
              : 'bg-[var(--surface-2)] text-[var(--text-muted)] cursor-not-allowed',
          ].join(' ')}
        >
          {disabled ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
        </button>
      </div>
    </div>
  )
}
