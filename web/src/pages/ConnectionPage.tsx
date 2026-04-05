import toast from 'react-hot-toast'
import { useState } from 'react'

import { useSettingsStore } from '../store/settingsStore'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'

export function ConnectionPage() {
  const backendUrl = useSettingsStore((s) => s.backendUrl)
  const setBackendUrl = useSettingsStore((s) => s.setBackendUrl)
  const [draft, setDraft] = useState(backendUrl)

  function save() {
    setBackendUrl(draft.replace(/\/$/, ''))
    toast.success('Backend URL uložena')
  }

  return (
    <div className="flex flex-col gap-4">
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
      <p className="text-xs text-[var(--text-muted)]">
        Toto nastavení je uloženo pouze v prohlížeči (localStorage) a není odesíláno na server.
      </p>
    </div>
  )
}
