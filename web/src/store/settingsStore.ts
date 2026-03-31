import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsState {
  backendUrl: string
  setBackendUrl: (url: string) => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      backendUrl: 'http://localhost:8001',
      setBackendUrl: (url) => set({ backendUrl: url }),
    }),
    { name: 'dautuu-settings' }
  )
)
