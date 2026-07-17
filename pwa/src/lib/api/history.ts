import { apiFetch, qs } from './client'

import type { BrowseHistoryItem, SavedSearch } from '../types'

// ── History ───────────────────────────────────────────────────────────

export const history = {
  list: (params: { limit?: number; offset?: number } = {}) =>
    apiFetch<{ items: BrowseHistoryItem[]; total: number }>(
      `/api/history/${qs(params as Record<string, unknown>)}`,
    ),

  record: (data: {
    source: string
    source_id: string
    title: string
    thumb?: string
    gid?: number
    token?: string
  }) =>
    apiFetch<{ status: string }>('/api/history/', { method: 'POST', body: JSON.stringify(data) }),

  clear: () => apiFetch<{ status: string }>('/api/history/', { method: 'DELETE' }),

  delete: (id: number) => apiFetch<{ status: string }>(`/api/history/${id}`, { method: 'DELETE' }),
}

// ── Saved Searches ────────────────────────────────────────────────────

export const savedSearches = {
  list: () => apiFetch<{ searches: SavedSearch[] }>('/api/search/saved'),

  create: (data: { name: string; query: string; params: Record<string, unknown> }) =>
    apiFetch<SavedSearch>('/api/search/saved', { method: 'POST', body: JSON.stringify(data) }),

  delete: (id: number) =>
    apiFetch<{ status: string }>(`/api/search/saved/${id}`, { method: 'DELETE' }),

  rename: (id: number, name: string) =>
    apiFetch<{ status: string }>(`/api/search/saved/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),
}
