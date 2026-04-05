import { api } from './client'

export interface McpServerOut {
  id: string
  name: string
  url: string
  headers: Record<string, string>
  enabled: boolean
  transport_type: 'streamable_http' | 'sse'
}

export interface McpServerCreate {
  name: string
  url: string
  headers: Record<string, string>
  enabled: boolean
  transport_type: 'streamable_http' | 'sse'
}

export interface McpToolInfo {
  name: string
  description: string
}

export interface McpTestResult {
  ok: boolean
  tools_count: number
  tools: McpToolInfo[]
}

export async function listMcpServers(): Promise<McpServerOut[]> {
  const res = await api.get('/mcp-servers')
  return res.data
}

export async function createMcpServer(data: McpServerCreate): Promise<McpServerOut> {
  const res = await api.post('/mcp-servers', data)
  return res.data
}

export async function updateMcpServer(
  id: string,
  data: Partial<McpServerCreate>,
): Promise<McpServerOut> {
  const res = await api.patch(`/mcp-servers/${id}`, data)
  return res.data
}

export async function deleteMcpServer(id: string): Promise<void> {
  await api.delete(`/mcp-servers/${id}`)
}

export async function testMcpServer(id: string): Promise<McpTestResult> {
  const res = await api.post(`/mcp-servers/${id}/test`)
  return res.data
}
