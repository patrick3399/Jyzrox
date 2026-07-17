import { apiFetch, encodeOpaquePathId, galleryApiPath, qs } from './client'

import type {
  Gallery,
  GalleryImage,
  GalleryListResponse,
  GallerySearchParams,
  ReadProgress,
  ArtistSummary,
  ArtistDetail,
  ArtistImageItem,
  LibraryFile,
} from '../types'

// ── Library ───────────────────────────────────────────────────────────

export const library = {
  getSources: (init?: RequestInit) =>
    apiFetch<{ value: string; label: string }[]>('/api/library/galleries/sources', init),

  getCategories: (init?: RequestInit) =>
    apiFetch<{ categories: string[] }>('/api/library/galleries/categories', init),

  getGalleries: (params: GallerySearchParams = {}, init?: RequestInit) =>
    apiFetch<GalleryListResponse>(
      `/api/library/galleries${qs(params as Record<string, unknown>)}`,
      init,
    ),

  getGallery: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<Gallery>(galleryApiPath(source, sourceId), init),

  getImages: (
    source: string,
    sourceId: string,
    opts?: { page?: number; limit?: number },
    init?: RequestInit,
  ) => {
    const params = new URLSearchParams()
    if (opts?.page) params.set('page', String(opts.page))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return apiFetch<{
      gallery_id: number
      images: GalleryImage[]
      total?: number
      page?: number
      has_next?: boolean
      favorited_image_ids?: number[]
    }>(`${galleryApiPath(source, sourceId, '/images')}${qs ? `?${qs}` : ''}`, init)
  },

  updateGallery: (
    source: string,
    sourceId: string,
    patch: {
      favorited?: boolean
      rating?: number
      title?: string
      title_jpn?: string
      category?: string
      in_reading_list?: boolean
    },
    init?: RequestInit,
  ) =>
    apiFetch<Gallery>(galleryApiPath(source, sourceId), {
      method: 'PATCH',
      body: JSON.stringify(patch),
      ...init,
    }),

  batchGalleries: (
    body: {
      action:
        | 'delete'
        | 'favorite'
        | 'unfavorite'
        | 'rate'
        | 'add_to_collection'
        | 'add_tags'
        | 'remove_tags'
        | 'add_to_reading_list'
        | 'remove_from_reading_list'
      gallery_ids: number[]
      rating?: number
      collection_id?: number
      tags?: string[]
    },
    init?: RequestInit,
  ) =>
    apiFetch<{ status: string; affected: number; deleted_dirs?: number }>(
      '/api/library/galleries/batch',
      {
        method: 'POST',
        body: JSON.stringify(body),
        ...init,
      },
    ),

  deleteGallery: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{ status: string; deleted_files: number }>(galleryApiPath(source, sourceId), {
      method: 'DELETE',
      ...init,
    }),

  getProgress: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<ReadProgress>(galleryApiPath(source, sourceId, '/progress'), init),

  saveProgress: (source: string, sourceId: string, last_page: number, init?: RequestInit) =>
    apiFetch<{ status: string }>(galleryApiPath(source, sourceId, '/progress'), {
      method: 'POST',
      body: JSON.stringify({ last_page }),
      ...init,
    }),

  readingStats: (days = 30) =>
    apiFetch<{
      days: number
      trend: Array<{ date: string; events: number; galleries: number }>
      top_tags: Array<{ namespace: string; name: string; reads: number }>
      unfinished: Array<{
        gallery_id: number
        source: string
        source_id: string
        title: string | null
        last_page: number
        pages: number
        last_read_at: string
      }>
    }>(`/api/library/stats${qs({ days })}`),

  getGalleryTags: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{
      gallery_id: number
      tags: Array<{
        namespace: string
        name: string
        confidence: number
        source: string
      }>
    }>(galleryApiPath(source, sourceId, '/tags'), init),

  getArtists: (
    params: { q?: string; source?: string; sort?: string; page?: number; limit?: number } = {},
    init?: RequestInit,
  ) =>
    apiFetch<{ artists: ArtistSummary[]; total: number }>(
      `/api/library/artists${qs(params as Record<string, unknown>)}`,
      init,
    ),

  getArtistSummary: (artistId: string, init?: RequestInit) =>
    apiFetch<ArtistDetail>(`/api/library/artists/${encodeURIComponent(artistId)}/summary`, init),

  getArtistImages: (
    artistId: string,
    params: { page?: number; limit?: number; sort?: 'newest' | 'oldest' } = {},
    init?: RequestInit,
  ) =>
    apiFetch<{
      artist_id: string
      images: ArtistImageItem[]
      total: number
      page: number
      has_next: boolean
    }>(
      `/api/library/artists/${encodeURIComponent(artistId)}/images${qs(params as Record<string, unknown>)}`,
      init,
    ),

  listGalleryFiles: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<{
      gallery_id: number
      source: string
      source_id: string
      title: string
      category: string | null
      files: LibraryFile[]
      total_files: number
    }>(`/api/library/files/${encodeURIComponent(source)}/${encodeOpaquePathId(sourceId)}`, init),

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

  trashList: (params: { limit?: number; offset?: number } = {}, init?: RequestInit) =>
    apiFetch<{ total: number; galleries: Gallery[] }>(
      `/api/library/trash${qs(params as Record<string, unknown>)}`,
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

  emptyTrash: (init?: RequestInit) =>
    apiFetch<{ status: string; affected: number }>('/api/library/trash/empty', {
      method: 'POST',
      ...init,
    }),

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
      phash: string
      distance: number
    }>
  }> =>
    apiFetch(`/api/library/images/${imageId}/similar?threshold=${threshold}&limit=${limit}`, init),
}
