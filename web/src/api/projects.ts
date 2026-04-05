import { api } from './client'

export interface ProjectOut {
  id: string
  name: string
  instructions: string | null
}

export async function listProjects(): Promise<ProjectOut[]> {
  const res = await api.get<ProjectOut[]>('/projects')
  return res.data
}

export async function createProject(name: string, instructions?: string): Promise<ProjectOut> {
  const res = await api.post<ProjectOut>('/projects', { name, instructions: instructions ?? null })
  return res.data
}

export async function updateProject(
  id: string,
  data: { name?: string; instructions?: string | null }
): Promise<ProjectOut> {
  const res = await api.patch<ProjectOut>(`/projects/${id}`, data)
  return res.data
}

export async function deleteProject(id: string): Promise<void> {
  await api.delete(`/projects/${id}`)
}
