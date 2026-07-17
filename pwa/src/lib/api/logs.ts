import { apiFetch } from './client'

import type { LogEntry, LogLevelConfig } from '../types'

// ── Logs ──────────────────────────────────────────────────────────────

export const logs = {
  list: (params?: {
    level?: string[]
    source?: string
    search?: string
    limit?: number
    offset?: number
  }) => {
    const sp = new URLSearchParams()
    if (params?.level) params.level.forEach((l) => sp.append('level', l))
    if (params?.source) sp.set('source', params.source)
    if (params?.search) sp.set('search', params.search)
    if (params?.limit) sp.set('limit', String(params.limit))
    if (params?.offset) sp.set('offset', String(params.offset))
    const qs = sp.toString()
    return apiFetch<{ logs: LogEntry[]; total: number; has_more: boolean }>(
      `/api/logs/${qs ? `?${qs}` : ''}`,
    )
  },
  clear: () => apiFetch<{ status: string; deleted: number }>('/api/logs/', { method: 'DELETE' }),
  getLevels: () => apiFetch<LogLevelConfig>('/api/logs/levels'),
  setLevel: (source: string, level: string) =>
    apiFetch<{ source: string; level: string }>('/api/logs/levels', {
      method: 'PATCH',
      body: JSON.stringify({ source, level }),
    }),
  getRetention: () => apiFetch<{ max_entries: number }>('/api/logs/retention'),
  setRetention: (data: { max_entries: number }) =>
    apiFetch<{ max_entries: number }>('/api/logs/retention', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
}

export const galleryDl = {
  getVersion: () =>
    apiFetch<{ current: string | null; latest: string | null }>('/api/admin/gallery-dl/version'),
  upgrade: (version?: string) =>
    apiFetch<{ job_id: string }>('/api/admin/gallery-dl/upgrade', {
      method: 'POST',
      body: JSON.stringify(version ? { version } : {}),
    }),
  rollback: () =>
    apiFetch<{ job_id: string }>('/api/admin/gallery-dl/rollback', { method: 'POST' }),
}
