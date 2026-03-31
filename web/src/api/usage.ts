import { api } from './client'

export interface ModelStats {
  provider: string
  model: string
  operation: string
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number | null
}

export interface DailyStats {
  day: string
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number | null
}

export interface UsageStats {
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost_usd: number | null
  by_model: ModelStats[]
  by_day: DailyStats[]
}

export async function fetchUsageStats(): Promise<UsageStats> {
  const res = await api.get<UsageStats>('/usage/stats')
  return res.data
}
