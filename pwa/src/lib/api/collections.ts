import { apiFetch, qs } from './client'

import type { Collection, Gallery } from '../types'

// ── Collections ──────────────────────────────────────────────────────

export const collections = {
  list: () => apiFetch<{ collections: Collection[] }>('/api/collections/'),

  get: (id: number, params: { page?: number; limit?: number } = {}) =>
    apiFetch<{
      id: number
      name: string
      description: string | null
      cover_gallery_id: number | null
      gallery_count: number
      galleries: Array<Gallery & { position: number; added_to_collection_at: string | null }>
      page: number
      has_next: boolean
      created_at: string | null
      updated_at: string | null
    }>(`/api/collections/${id}${qs(params as Record<string, unknown>)}`),

  create: (data: { name: string; description?: string }) =>
    apiFetch<{ id: number; name: string; description: string | null; created_at: string | null }>(
      '/api/collections/',
      {
        method: 'POST',
        body: JSON.stringify(data),
      },
    ),

  update: (id: number, patch: { name?: string; description?: string; cover_gallery_id?: number }) =>
    apiFetch<{ status: string }>(`/api/collections/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  delete: (id: number) =>
    apiFetch<{ status: string }>(`/api/collections/${id}`, {
      method: 'DELETE',
    }),

  addGalleries: (id: number, gallery_ids: number[]) =>
    apiFetch<{ status: string; added: number }>(`/api/collections/${id}/galleries`, {
      method: 'POST',
      body: JSON.stringify({ gallery_ids }),
    }),

  removeGallery: (id: number, galleryId: number) =>
    apiFetch<{ status: string }>(`/api/collections/${id}/galleries/${galleryId}`, {
      method: 'DELETE',
    }),
}
