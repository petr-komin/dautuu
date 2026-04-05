import { api } from './client'

export interface ConversationOut {
  id: string
  title: string
}

export interface MessageOut {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  model: string | null
}

export async function listConversations(): Promise<ConversationOut[]> {
  const res = await api.get<ConversationOut[]>('/chat/conversations')
  return res.data
}

export async function getMessages(conversationId: string): Promise<MessageOut[]> {
  const res = await api.get<MessageOut[]>(`/chat/conversations/${conversationId}/messages`)
  return res.data
}

export type ToolEvent =
  | { type: 'search'; query: string }
  | { type: 'tool'; name: string; path: string }

export async function sendMessageStream(params: {
  conversationId: string | null
  message: string
  provider: string
  model: string
  webSearch: boolean
  onChunk: (chunk: string) => void
  onToolEvent: (event: ToolEvent) => void
  onDone: (conversationId: string) => void
}): Promise<void> {
  const token = (await import('../store/authStore')).useAuthStore.getState().token

  const res = await fetch('/api/v1/chat/send', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      conversation_id: params.conversationId,
      message: params.message,
      provider: params.provider,
      model: params.model,
      stream: true,
      web_search: params.webSearch,
    }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Chyba při komunikaci s backendem')
  }

  const convId = res.headers.get('X-Conversation-Id') ?? params.conversationId ?? ''

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const text = decoder.decode(value, { stream: true })
    for (const line of text.split('\n')) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6)

      if (data === '[DONE]') {
        params.onDone(convId)
        return
      }

      // Web search: [SEARCHING:query]
      const searchMatch = data.match(/^\[SEARCHING:(.+)\]$/)
      if (searchMatch) {
        params.onToolEvent({ type: 'search', query: searchMatch[1] })
        continue
      }

      // File tool: [TOOL:tool_name:path]
      const toolMatch = data.match(/^\[TOOL:([^:]+):?(.*)\]$/)
      if (toolMatch) {
        params.onToolEvent({ type: 'tool', name: toolMatch[1], path: toolMatch[2] })
        continue
      }

      params.onChunk(data)
    }
  }

  params.onDone(convId)
}
