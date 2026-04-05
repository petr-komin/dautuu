import { Check } from 'lucide-react'
import toast from 'react-hot-toast'
import { useState, useEffect } from 'react'

import { Card, CardContent, CardHeader } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { fetchProviders, fetchPreference, savePreference, type ProviderInfo, type ModelPreset } from '../api/auth'

export function ModelPage() {
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
      .catch(() => toast.error('Nepodařilo se načíst nastavení'))
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

  const availableByProvider = providers
    .filter((p) => p.available)

  if (availableByProvider.length === 0) {
    return (
      <p className="text-sm text-[var(--text-muted)]">
        Žádný provider není dostupný. Nastav API klíče v <code>.env</code> na serveru.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {availableByProvider.map((provider: ProviderInfo) => (
        <Card key={provider.id}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--text)] capitalize">{provider.id}</span>
              <Badge variant="success">dostupný</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2">
              {provider.models.map((preset: ModelPreset) => {
                const active = preset.provider === activeProvider && preset.model === activeModel
                return (
                  <button
                    key={`${preset.provider}/${preset.model}`}
                    onClick={() => handleSelect(preset.provider, preset.model)}
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
                    {active && <Check size={14} className="text-[var(--accent)]" />}
                  </button>
                )
              })}
            </div>
          </CardContent>
        </Card>
      ))}
      <p className="text-xs text-[var(--text-muted)]">
        Dostupné modely závisí na API klíčích nastavených v <code>.env</code> na serveru.
      </p>
    </div>
  )
}
