import { api } from './client'

export interface DocumentOut {
  id: string
  title: string
  project_id: string | null
  source_text: string
  content: string
  created_at: string
  updated_at: string
}

export interface DocumentCreate {
  title?: string
  project_id?: string | null
  source_text?: string
  content?: string
}

export interface DocumentUpdate {
  title?: string
  project_id?: string | null
  source_text?: string
  content?: string
}

export const documentsApi = {
  list: async () => {
    const { data } = await api.get<DocumentOut[]>('/api/v1/documents')
    return data
  },
  get: async (id: string) => {
    const { data } = await api.get<DocumentOut>(`/api/v1/documents/${id}`)
    return data
  },
  create: async (payload: DocumentCreate) => {
    const { data } = await api.post<DocumentOut>('/api/v1/documents', payload)
    return data
  },
  update: async (id: string, payload: DocumentUpdate) => {
    const { data } = await api.put<DocumentOut>(`/api/v1/documents/${id}`, payload)
    return data
  },
  delete: async (id: string) => {
    await api.delete(`/api/v1/documents/${id}`)
  },
}

export interface DocumentGenerateParams {
  prompt: string
  model: string
  provider: string
}

export async function generateDocumentStream(
  docId: string,
  params: DocumentGenerateParams,
  onDelta: (text: string) => void,
  onError: (msg: string) => void,
  onDone: () => void
) {
  const token = localStorage.getItem('dautuu:token')
  const res = await fetch(`/api/v1/documents/${docId}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(params),
  })

  if (!res.ok) {
    let err = `HTTP ${res.status}`
    try {
      const e = await res.json()
      err = e.detail || err
    } catch {}
    onError(err)
    return
  }

  const reader = res.body?.getReader()
  if (!reader) return

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        if (!raw) continue

        if (raw === '[DONE]') {
          onDone()
          return
        }

        try {
          const parsed = JSON.parse(raw)
          if (parsed.type === 'delta') {
            onDelta(parsed.delta)
          } else if (parsed.type === 'error') {
            onError(parsed.error)
          } else if (parsed.type === 'done') {
            onDone()
          }
        } catch (e) {
          console.error('SSE parse error:', e)
        }
      }
    }
  } finally {
    reader.releaseLock()
    onDone()
  }
}