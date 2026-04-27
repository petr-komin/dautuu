import { api } from './client'

export interface ConversationOut {
  id: string
  title: string
  project_id: string | null
}

export interface MessageOut {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  model: string | null
  tool_data?: {
    citations?: string[]
    num_sources_used?: number
    reasoning_tokens?: number
  } | null
}

export async function listConversations(projectId?: string | null): Promise<ConversationOut[]> {
  const params = projectId !== undefined ? { project_id: projectId ?? undefined } : {}
  const res = await api.get<ConversationOut[]>('/chat/conversations', { params })
  return res.data
}

export async function createConversation(title: string, projectId?: string | null): Promise<ConversationOut> {
  const res = await api.post<ConversationOut>('/chat/conversations', {
    title,
    project_id: projectId ?? null,
  })
  return res.data
}

export async function assignConversation(conversationId: string, projectId: string | null): Promise<ConversationOut> {
  const res = await api.patch<ConversationOut>(`/chat/conversations/${conversationId}`, {
    project_id: projectId,
  })
  return res.data
}

export async function getMessages(conversationId: string): Promise<MessageOut[]> {
  const res = await api.get<MessageOut[]>(`/chat/conversations/${conversationId}/messages`)
  return res.data
}

export type ToolEvent =
  | { type: 'search'; query: string }
  | { type: 'tool'; name: string; path: string }

export interface CitationsEvent {
  citations: string[]
  num_sources_used: number
}

export interface RoutingEvent {
  web: boolean
  history: boolean
  email: boolean
  reasoning: string
  took_ms: number
  fallback: boolean
}

export interface GrokSearchOptions {
  enabled: boolean
  mode?: 'off' | 'on' | 'auto'
  maxResults?: number
  sources?: string[]               // ["web", "x", "news", "rss"]
  fromDate?: string                // ISO YYYY-MM-DD
  toDate?: string
  allowedDomains?: string[]
  excludedDomains?: string[]
}

export async function sendMessageStream(params: {
  conversationId: string | null
  message: string
  provider: string
  model: string
  webSearch: boolean
  webSearchBackend?: 'tavily' | 'grok'
  grokSearch?: GrokSearchOptions | boolean
  grokReasoningEffort?: 'low' | 'high' | null
  routingMode?: 'manual' | 'auto'
  projectId?: string | null
  onChunk: (chunk: string) => void
  onToolEvent: (event: ToolEvent) => void
  onCitations?: (ev: CitationsEvent) => void
  onRouting?: (ev: RoutingEvent) => void
  onDone: (conversationId: string) => void
}): Promise<void> {
  const token = (await import('../store/authStore')).useAuthStore.getState().token

  // Backwards-compat: grokSearch může být bool (jen on/off) nebo plný objekt
  const gs: GrokSearchOptions =
    typeof params.grokSearch === 'boolean'
      ? { enabled: params.grokSearch }
      : (params.grokSearch ?? { enabled: false })

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
      grok_search: gs.enabled,
      grok_search_mode: gs.mode ?? 'auto',
      grok_search_max_results: gs.maxResults ?? 15,
      grok_search_sources: gs.sources ?? null,
      grok_search_from_date: gs.fromDate ?? null,
      grok_search_to_date: gs.toDate ?? null,
      grok_allowed_domains: gs.allowedDomains ?? null,
      grok_excluded_domains: gs.excludedDomains ?? null,
      grok_reasoning_effort: params.grokReasoningEffort ?? null,
      routing_mode: params.routingMode ?? 'manual',
      web_search_backend: params.webSearchBackend ?? 'tavily',
      project_id: params.projectId ?? null,
    }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Chyba při komunikaci s backendem')
  }

  const convId = res.headers.get('X-Conversation-Id') ?? params.conversationId ?? ''

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent: string | null = null

  const handleData = (data: string) => {
    if (data === '[DONE]') {
      params.onDone(convId)
      return 'done'
    }
    // Citations SSE event
    if (currentEvent === 'citations') {
      try {
        const parsed = JSON.parse(data) as CitationsEvent
        params.onCitations?.(parsed)
      } catch {
        /* ignore malformed */
      }
      return 'continue'
    }
    // Routing SSE event
    if (currentEvent === 'routing') {
      try {
        const parsed = JSON.parse(data) as RoutingEvent
        params.onRouting?.(parsed)
      } catch {
        /* ignore malformed */
      }
      return 'continue'
    }
    // Web search: [SEARCHING:query]
    const searchMatch = data.match(/^\[SEARCHING:(.+)\]$/)
    if (searchMatch) {
      params.onToolEvent({ type: 'search', query: searchMatch[1] })
      return 'continue'
    }
    // File tool: [TOOL:tool_name:path]
    const toolMatch = data.match(/^\[TOOL:([^:]+):?(.*)\]$/)
    if (toolMatch) {
      params.onToolEvent({ type: 'tool', name: toolMatch[1], path: toolMatch[2] })
      return 'continue'
    }
    params.onChunk(data)
    return 'continue'
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE: oddělené prázdným řádkem (\n\n)
    let sepIdx: number
    while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, sepIdx)
      buffer = buffer.slice(sepIdx + 2)
      let blockEvent: string | null = null
      const dataLines: string[] = []
      for (const ln of block.split('\n')) {
        if (ln.startsWith('event: ')) {
          blockEvent = ln.slice(7).trim()
        } else if (ln.startsWith('data: ')) {
          dataLines.push(ln.slice(6))
        }
      }
      currentEvent = blockEvent
      if (dataLines.length === 0) continue
      const data = dataLines.join('\n')
      const action = handleData(data)
      currentEvent = null
      if (action === 'done') return
    }
  }

  params.onDone(convId)
}

