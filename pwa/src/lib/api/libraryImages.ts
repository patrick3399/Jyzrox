import { apiFetch, galleryApiPath, qs } from './client'

import type { GalleryImage } from '../types'

export const libraryImages = {
  deleteImage: (source: string, sourceId: string, pageNum: number, init?: RequestInit) =>
    apiFetch<{ status: string; remaining_pages: number }>(
      galleryApiPath(source, sourceId, '/delete-image'),
      { method: 'POST', body: JSON.stringify({ page_num: pageNum }), ...init },
    ),

  hideImage: (imageId: number, init?: RequestInit) =>
    apiFetch<{ status: string; remaining_pages: number }>(`/api/library/images/${imageId}/hide`, {
      method: 'POST',
      ...init,
    }),

  restoreImage: (imageId: number, init?: RequestInit) =>
    apiFetch<{ status: string; remaining_pages: number }>(
      `/api/library/images/${imageId}/restore`,
      {
        method: 'POST',
        ...init,
      },
    ),

  hideImagesBatch: (source: string, sourceId: string, imageIds: number[], init?: RequestInit) =>
    apiFetch<{ status: string; hidden: number; remaining_pages: number }>(
      galleryApiPath(source, sourceId, '/images/hide-batch'),
      { method: 'POST', body: JSON.stringify({ image_ids: imageIds }), ...init },
    ),

  restoreImagesBatch: (source: string, sourceId: string, imageIds: number[], init?: RequestInit) =>
    apiFetch<{ status: string; restored: number; remaining_pages: number }>(
      galleryApiPath(source, sourceId, '/images/restore-batch'),
      { method: 'POST', body: JSON.stringify({ image_ids: imageIds }), ...init },
    ),

  listHidden: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{
      gallery_id: number
      images: GalleryImage[]
      favorited_image_ids: number[]
    }>(galleryApiPath(source, sourceId, '/hidden'), init),

  listExcluded: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{
      gallery_id: number
      excluded: Array<{ blob_sha256: string; excluded_at: string | null }>
    }>(galleryApiPath(source, sourceId, '/excluded'), init),

  restoreExcluded: (source: string, sourceId: string, sha256: string, init?: RequestInit) =>
    apiFetch<{ status: string }>(
      `${galleryApiPath(source, sourceId, '/excluded')}/${encodeURIComponent(sha256)}`,
      { method: 'DELETE', ...init },
    ),

  favoriteImage: (imageId: number, init?: RequestInit) =>
    apiFetch<{ status: string }>(`/api/library/images/${imageId}/favorite`, {
      method: 'POST',
      ...init,
    }),

  unfavoriteImage: (imageId: number, init?: RequestInit) =>
    apiFetch<{ status: string }>(`/api/library/images/${imageId}/favorite`, {
      method: 'DELETE',
      ...init,
    }),

  browseImages: (
    params: {
      tags?: string[]
      exclude_tags?: string[]
      cursor?: string
      limit?: number
      sort?: 'newest' | 'oldest'
      gallery_id?: number
      source?: string
      category?: string
      jump_at?: string
      favorited?: boolean
    } = {},
    init?: RequestInit,
  ) =>
    apiFetch<import('../types').ImageBrowserResponse>(
      `/api/library/images${qs(params as Record<string, unknown>)}`,
      init,
    ),

  imageTimeRange: (
    params: {
      tags?: string[]
      exclude_tags?: string[]
      source?: string
      category?: string
      gallery_id?: number
      favorited?: boolean
    } = {},
    init?: RequestInit,
  ) =>
    apiFetch<import('../types').ImageTimeRangeResponse>(
      `/api/library/images/time_range${qs(params as Record<string, unknown>)}`,
      init,
    ),

  imageTimelinePercentiles: (
    params: {
      tags?: string[]
      exclude_tags?: string[]
      source?: string
      category?: string
      gallery_id?: number
      buckets?: number
      favorited?: boolean
    } = {},
    init?: RequestInit,
  ) =>
    apiFetch<import('../types').TimelinePercentilesResponse>(
      `/api/library/images/timeline_percentiles${qs(params as Record<string, unknown>)}`,
      init,
    ),
}
