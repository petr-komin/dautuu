import { Check, Cpu, Server } from 'lucide-react'
import toast from 'react-hot-toast'
import { useState, useEffect } from 'react'

import { useSettingsStore } from '../store/settingsStore'
import { Card, CardContent, CardHeader } from '../components/ui/Card'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import {
  fetchProviders,
  fetchPreference,
  savePreference,
  type ProviderInfo,
  type ModelPreset,
} from '../api/auth'

// -------------------------------------------------------------------------
// Sekce: Backend URL
// -------------------------------------------------------------------------

function BackendSection() {
  const backendUrl = useSettingsStore((s) => s.backendUrl)
  const setBackendUrl = useSettingsStore((s) => s.setBackendUrl)
  const [draft, setDraft] = useState(backendUrl)

  function save() {
    setBackendUrl(draft.replace(/\/$/, ''))
    toast.success('Backend URL uložena')
  }

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-medium text-[var(--text)]">Backend URL</span>
      <div className="flex gap-2">
        <Input
          className="flex-1 font-mono"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="http://localhost:8001"
          hint="URL kde běží dautuu backend (FastAPI)"
        />
        <Button size="sm" onClick={save}>
          Uložit
        </Button>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------
// Sekce: Výchozí model
// -------------------------------------------------------------------------

interface DefaultModelSectionProps {
  providers: ProviderInfo[]
  activeProvider: string
  activeModel: string
  onSelect: (provider: string, model: string) => void
}

function DefaultModelSection({ providers, activeProvider, activeModel, onSelect }: DefaultModelSectionProps) {
  const availableModels = providers
    .filter((p) => p.available)
    .flatMap((p) => p.models)

  if (availableModels.length === 0) {
    return (
      <p className="text-sm text-[var(--text-muted)]">
        Žádný provider není dostupný. Nastav API klíče v <code>.env</code> na serveru.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-2">
        {availableModels.map((preset: ModelPreset) => {
          const active = preset.provider === activeProvider && preset.model === activeModel
          return (
            <button
              key={`${preset.provider}/${preset.model}`}
              onClick={() => onSelect(preset.provider, preset.model)}
              className={[
                'flex items-center justify-between px-4 py-3 rounded-lg border text-sm transition-colors text-left',
                active
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--text)]'
                  : 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--text-muted)]',
              ].join(' ')}
            >
              <div className="flex flex-col gap-0.5">
                <span className={active ? 'text-[var(--text)]' : ''}>{preset.label}</span>
                <span className="text-xs font-mono text-[var(--text-muted)]">{preset.model}</span>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="default">{preset.provider}</Badge>
                {active && <Check size={14} className="text-[var(--accent)]" />}
              </div>
            </button>
          )
        })}
      </div>
      <p className="text-xs text-[var(--text-muted)]">
        Dostupné modely závisí na API klíčích nastavených v <code>.env</code> na serveru.
      </p>
    </div>
  )
}

// -------------------------------------------------------------------------
// Hlavní stránka
// -------------------------------------------------------------------------

export function SettingsPage() {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [activeProvider, setActiveProvider] = useState('')
  const [activeModel, setActiveModel] = useState('')

  useEffect(() => {
    Promise.all([fetchProviders(), fetchPreference()])
      .then(([providerList, pref]) => {
        setProviders(providerList)
        setActiveProvider(pref.provider)
        setActiveModel(pref.model)
      })
      .catch(() => toast.error('Nepodařilo se načíst nastavení ze serveru'))
  }, [])

  async function handleSelect(provider: string, model: string) {
    setActiveProvider(provider)
    setActiveModel(model)
    try {
      await savePreference(provider, model)
      toast.success('Model uložen')
    } catch {
      toast.error('Nepodařilo se uložit model')
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text)]">Nastavení</h1>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
            <Server size={16} className="text-[var(--accent)]" />
            Připojení
          </div>
        </CardHeader>
        <CardContent>
          <BackendSection />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
            <Cpu size={16} className="text-[var(--accent)]" />
            Výchozí model
          </div>
        </CardHeader>
        <CardContent>
          <DefaultModelSection
            providers={providers}
            activeProvider={activeProvider}
            activeModel={activeModel}
            onSelect={handleSelect}
          />
        </CardContent>
      </Card>
    </div>
  )
}
