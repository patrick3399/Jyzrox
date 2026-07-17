import { apiFetch, qs } from './client'

import type { Dataset, DatasetDetail, DatasetFilterConfig, DatasetFilterReport, DatasetSelection } from '../types'

// ── AI training datasets ────────────────────────────────────────────

export const datasets = {
  list: () => apiFetch<{ datasets: Dataset[] }>('/api/datasets/'),

  get: (
    id: number,
    params: { state?: 'included' | 'excluded'; page?: number; limit?: number } = {},
  ) => apiFetch<DatasetDetail>(`/api/datasets/${id}${qs(params as Record<string, unknown>)}`),

  create: (data: { name: string; description?: string } & DatasetSelection) =>
    apiFetch<Dataset & { added: number; tag_query_truncated: boolean }>('/api/datasets/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (
    id: number,
    patch: { name?: string; description?: string | null; tag_threshold?: number },
  ) =>
    apiFetch<{ status: string }>(`/api/datasets/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  delete: (id: number) => apiFetch<{ status: string }>(`/api/datasets/${id}`, { method: 'DELETE' }),

  addMembers: (id: number, selection: DatasetSelection) =>
    apiFetch<{ status: string; added: number; tag_query_truncated: boolean }>(
      `/api/datasets/${id}/members`,
      {
        method: 'POST',
        body: JSON.stringify(selection),
      },
    ),

  excludeImage: (id: number, imageId: number) =>
    apiFetch<{ status: string; state: 'excluded' }>(`/api/datasets/${id}/images/${imageId}`, {
      method: 'DELETE',
    }),

  previewFilters: (id: number, filters: DatasetFilterConfig) =>
    apiFetch<DatasetFilterReport>(`/api/datasets/${id}/filters/preview`, {
      method: 'POST',
      body: JSON.stringify(filters),
    }),

  applyFilters: (id: number, filters: DatasetFilterConfig) =>
    apiFetch<DatasetFilterReport & { changed: number }>(`/api/datasets/${id}/filters/apply`, {
      method: 'POST',
      body: JSON.stringify(filters),
    }),

  updateCaption: (id: number, imageId: number, caption: string | null) =>
    apiFetch<{ status: string; caption: string | null }>(
      `/api/datasets/${id}/images/${imageId}/caption`,
      { method: 'PATCH', body: JSON.stringify({ caption }) },
    ),

  batchCaptions: (
    id: number,
    data:
      | { operation: 'prepend_trigger'; trigger_word: string }
      | { operation: 'search_replace'; search: string; replacement: string },
  ) =>
    apiFetch<{ status: string; changed: number }>(`/api/datasets/${id}/captions/batch`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  generateCaptions: (id: number, engine: 'florence2' | 'joycaption') =>
    apiFetch<{ status: string; job_id: string; engine: string }>(
      `/api/datasets/${id}/captions/generate`,
      { method: 'POST', body: JSON.stringify({ engine }) },
    ),
}
