import { api } from './client'

export interface LoginRequest {
  username: string // FastAPI OAuth2PasswordRequestForm používá "username"
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface ModelPreset {
  provider: string
  model: string
  label: string
}

export interface ProviderInfo {
  id: string
  available: boolean
  models: ModelPreset[]
}

export interface Preference {
  provider: string
  model: string
}

export async function login(data: LoginRequest): Promise<TokenResponse> {
  const form = new URLSearchParams()
  form.append('username', data.username)
  form.append('password', data.password)
  const res = await api.post<TokenResponse>('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return res.data
}

export async function register(data: RegisterRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>('/auth/register', data)
  return res.data
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const res = await api.get<{ providers: ProviderInfo[] }>('/providers')
  return res.data.providers
}

export async function fetchPreference(): Promise<Preference> {
  const res = await api.get<Preference>('/providers/preference')
  return res.data
}

export async function savePreference(provider: string, model: string): Promise<Preference> {
  const res = await api.put<Preference>('/providers/preference', { provider, model })
  return res.data
}

// -------------------------------------------------------------------------
// MCP API klíč
// -------------------------------------------------------------------------

export interface ApiKeyResponse {
  api_key: string
  user_id: string
}

/** Vrátí aktuální MCP API klíč (nebo null pokud ještě nebyl vygenerován). */
export async function fetchApiKey(): Promise<ApiKeyResponse | null> {
  try {
    const res = await api.get<ApiKeyResponse>('/auth/api-key')
    return res.data
  } catch (err: any) {
    if (err?.response?.status === 404) return null
    throw err
  }
}

/** Vygeneruje nový MCP API klíč (přepíše stávající). */
export async function generateApiKey(): Promise<ApiKeyResponse> {
  const res = await api.post<ApiKeyResponse>('/auth/api-key')
  return res.data
}
