import { Key, Copy, RefreshCw, Terminal, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { useState, useEffect } from 'react'

import { useSettingsStore } from '../store/settingsStore'
import { Button } from '../components/ui/Button'
import { fetchApiKey, generateApiKey, type ApiKeyResponse } from '../api/auth'

function CodeBlock({ children }: { children: string }) {
  function copy() {
    navigator.clipboard.writeText(children).then(() => toast.success('Zkopírováno'))
  }
  return (
    <div className="relative group">
      <pre className="rounded-lg bg-[var(--bg)] border border-[var(--border)] px-4 py-3 text-xs font-mono text-[var(--text-muted)] overflow-x-auto whitespace-pre">
        {children}
      </pre>
      <button
        onClick={copy}
        className="absolute top-2 right-2 p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity bg-[var(--surface-2)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]"
        title="Kopírovat"
      >
        <Copy size={12} />
      </button>
    </div>
  )
}

// ---- Main McpPage ----

export function McpPage() {
  const backendUrl = useSettingsStore((s) => s.backendUrl)
  const [apiKeyData, setApiKeyData] = useState<ApiKeyResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [showGuide, setShowGuide] = useState(false)

  useEffect(() => {
    fetchApiKey()
      .then(setApiKeyData)
      .catch(() => toast.error('Nepodařilo se načíst API klíč'))
      .finally(() => setLoading(false))
  }, [])

  async function handleGenerate() {
    setGenerating(true)
    try {
      const data = await generateApiKey()
      setApiKeyData(data)
      toast.success(apiKeyData ? 'API klíč přegenerován' : 'API klíč vygenerován')
    } catch {
      toast.error('Nepodařilo se vygenerovat API klíč')
    } finally {
      setGenerating(false)
    }
  }

  function copyKey() {
    if (!apiKeyData) return
    navigator.clipboard.writeText(apiKeyData.api_key).then(() => toast.success('API klíč zkopírován'))
  }

  const sseUrl = apiKeyData
    ? `${backendUrl}/api/v1/mcp/${apiKeyData.user_id}/sse`
    : `${backendUrl}/api/v1/mcp/{user_id}/sse`

  const opencodeConfig = apiKeyData
    ? JSON.stringify(
        {
          $schema: 'https://opencode.ai/config.json',
          mcp: {
            dautuu: {
              type: 'remote',
              url: sseUrl,
              oauth: false,
              headers: { Authorization: `Bearer ${apiKeyData.api_key}` },
            },
          },
        },
        null,
        2
      )
    : '{ /* nejprve vygeneruj API klíč */ }'

  const claudeConfig = apiKeyData
    ? JSON.stringify(
        {
          mcpServers: {
            dautuu: {
              transport: {
                type: 'sse',
                url: sseUrl,
                headers: { Authorization: `Bearer ${apiKeyData.api_key}` },
              },
            },
          },
        },
        null,
        2
      )
    : '{ /* nejprve vygeneruj API klíč */ }'

  return (
    <div className="flex flex-col gap-6">

      {/* API klíč */}
      <div className="flex flex-col gap-3">
        <span className="text-sm font-medium text-[var(--text)]">MCP API klíč</span>
        {loading ? (
          <p className="text-sm text-[var(--text-muted)]">Načítám...</p>
        ) : apiKeyData ? (
          <>
            <div className="flex gap-2">
              <div className="flex-1 flex items-center px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] font-mono text-xs text-[var(--text-muted)] overflow-hidden">
                <span className="truncate">{apiKeyData.api_key}</span>
              </div>
              <Button size="sm" variant="secondary" onClick={copyKey} title="Kopírovat klíč">
                <Copy size={14} />
              </Button>
              <Button size="sm" variant="ghost" onClick={handleGenerate} loading={generating} title="Přegenerovat klíč">
                <RefreshCw size={14} />
              </Button>
            </div>
            <p className="text-xs text-[var(--text-muted)]">
              Klíč lze kdykoliv přegenerovat — starý klíč přestane okamžitě fungovat.
            </p>
          </>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-[var(--text-muted)]">API klíč ještě nebyl vygenerován.</p>
            <div>
              <Button size="sm" onClick={handleGenerate} loading={generating}>
                <Key size={14} />
                Vygenerovat API klíč
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* SSE endpoint */}
      {apiKeyData && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-[var(--text)]">SSE endpoint</span>
          <CodeBlock>{sseUrl}</CodeBlock>
        </div>
      )}

      {/* Dostupné tools */}
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium text-[var(--text)]">Dostupné MCP tools</span>
        <div className="grid gap-1.5">
          {[
            { name: 'add_memory', desc: 'Uloží text jako vzpomínku (volitelně s kategorií a projektem)' },
            { name: 'search_memory', desc: 'Sémanticky vyhledá v paměti — volitelně jen v daném projektu' },
            { name: 'list_memories', desc: 'Vypíše posledních N vzpomínek — volitelně jen z daného projektu' },
            { name: 'delete_memory', desc: 'Smaže vzpomínku podle ID' },
          ].map((t) => (
            <div key={t.name} className="flex items-start gap-3 text-sm">
              <code className="shrink-0 px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] text-xs text-[var(--accent)] font-mono">
                {t.name}
              </code>
              <span className="text-[var(--text-muted)]">{t.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Návod */}
      <div className="border border-[var(--border)] rounded-lg overflow-hidden">
        <button
          onClick={() => setShowGuide((v) => !v)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
        >
          <div className="flex items-center gap-2">
            <Terminal size={14} className="text-[var(--accent)]" />
            Jak připojit MCP klienta
          </div>
          {showGuide
            ? <ChevronUp size={14} className="text-[var(--text-muted)]" />
            : <ChevronDown size={14} className="text-[var(--text-muted)]" />}
        </button>

        {showGuide && (
          <div className="px-4 pb-5 flex flex-col gap-5 border-t border-[var(--border)]">

            <div className="flex flex-col gap-2 pt-4">
              <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">OpenCode</span>
              <p className="text-xs text-[var(--text-muted)]">
                Přidej do <code className="text-[var(--text)]">~/.config/opencode/config.json</code>:
              </p>
              <CodeBlock>{opencodeConfig}</CodeBlock>
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">Claude Desktop</span>
              <p className="text-xs text-[var(--text-muted)]">
                Přidej do{' '}
                <code className="text-[var(--text)]">~/Library/Application Support/Claude/claude_desktop_config.json</code>{' '}
                (macOS) nebo{' '}
                <code className="text-[var(--text)]">%APPDATA%\Claude\claude_desktop_config.json</code>{' '}
                (Windows):
              </p>
              <CodeBlock>{claudeConfig}</CodeBlock>
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">Cursor / jiný MCP klient</span>
              <p className="text-xs text-[var(--text-muted)]">
                Použij <strong className="text-[var(--text)]">SSE transport</strong>, URL výše a header{' '}
                <code className="text-[var(--text)]">Authorization: Bearer {'<api_key>'}</code>.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">Filtrování dle projektu</span>
              <p className="text-xs text-[var(--text-muted)]">
                Všechny tools přijímají volitelný parametr <code className="text-[var(--text)]">project</code> — název projektu
                nebo workspace (např. <code className="text-[var(--text)]">"dautuu"</code>). Vzpomínky bez projektu jsou globální.
                Vyzvi AI asistenta, aby vždy předával projekt:
              </p>
              <CodeBlock>{`// Příklad — v system promptu OpenCode / Cursor:
// "Při práci na projektu 'dautuu' vždy předávej
//  project: 'dautuu' při volání MCP memory tools."

add_memory({ text: "...", project: "dautuu" })
search_memory({ query: "...", project: "dautuu" })
list_memories({ project: "dautuu" })`}</CodeBlock>
            </div>

          </div>
        )}
      </div>

    </div>
  )
}
