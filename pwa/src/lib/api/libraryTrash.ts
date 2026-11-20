import { apiFetch, galleryApiPath, qs } from './client'

import type {
  Gallery,
  TrashFilters,
  TrashGallery,
  TrashPurgeQueued,
  TrashSort,
  TrashSortDirection,
  TrashSummary,
  TrashPreview,
} from '../types'

export const libraryTrash = {
  trashList: (
    params: TrashFilters & {
      limit?: number
      offset?: number
      sort?: TrashSort
      direction?: TrashSortDirection
    } = {},
    init?: RequestInit,
  ) =>
    apiFetch<{ total: number; galleries: TrashGallery[] }>(
      `/api/library/trash${qs(params as Record<string, unknown>)}`,
      init,
    ),

  trashSummary: (filters: TrashFilters = {}, init?: RequestInit) =>
    apiFetch<TrashSummary>(
      `/api/library/trash/summary${qs(filters as Record<string, unknown>)}`,
      init,
    ),

  trashRestore: (
    body: { gallery_ids: number[] } | ({ all: true } & TrashFilters),
    init?: RequestInit,
  ) =>
    apiFetch<{ status: string; affected: number }>('/api/library/trash/restore', {
      method: 'POST',
      body: JSON.stringify(body),
      ...init,
    }),

  trashPurge: (galleryIds: number[], init?: RequestInit) =>
    apiFetch<TrashPurgeQueued>('/api/library/trash/purge', {
      method: 'POST',
      body: JSON.stringify({ gallery_ids: galleryIds }),
      ...init,
    }),

  trashPreview: (
    galleryId: number,
    params: { page?: number; limit?: number } = {},
    init?: RequestInit,
  ) =>
    apiFetch<TrashPreview>(
      `/api/library/trash/${galleryId}/preview${qs(params as Record<string, unknown>)}`,
      init,
    ),

  trashCount: (init?: RequestInit) => apiFetch<{ count: number }>('/api/library/trash/count', init),

  restore: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{ status: string }>(galleryApiPath(source, sourceId, '/restore'), {
      method: 'POST',
      ...init,
    }),

  permanentDelete: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{ status: string; affected: number; deleted_dirs: number }>(
      galleryApiPath(source, sourceId, '/permanent-delete'),
      {
        method: 'POST',
        ...init,
      },
    ),

  emptyTrash: (filters: TrashFilters = {}, init?: RequestInit) =>
    apiFetch<TrashPurgeQueued>(
      `/api/library/trash/empty${qs(filters as Record<string, unknown>)}`,
      {
        method: 'POST',
        ...init,
      },
    ),

  checkUpdate: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{
      status: string
      reason?: string
      gallery?: Gallery
      changed_fields?: string[]
      pages_diff?: { old: number; new: number } | null
    }>(galleryApiPath(source, sourceId, '/check-update'), { method: 'POST', ...init }),

  findSimilar: (
    imageId: number,
    threshold = 10,
    limit = 20,
    init?: RequestInit,
  ): Promise<{
    image_id: number
    phash: string
    similar: Array<{
      id: number
      gallery_id: number
      filename: string
      file_path: string
      thumb_path: string | null
      thumb_srcset?: string | null
      phash: string
      distance: number
    }>
  }> =>
    apiFetch(`/api/library/images/${imageId}/similar?threshold=${threshold}&limit=${limit}`, init),
}
