import { apiFetch, galleryApiPath, qs } from './client'

import type {
  Gallery,
  GalleryImage,
  GalleryListResponse,
  GallerySyncResult,
  GallerySearchParams,
  ReadProgress,
  ArtistSummary,
  ArtistDetail,
  ArtistImageItem,
  LibraryFacets,
} from '../types'

export const libraryGalleries = {
  getSources: (init?: RequestInit) =>
    apiFetch<{ value: string; label: string }[]>('/api/library/galleries/sources', init),

  getCategories: (init?: RequestInit) =>
    apiFetch<{ categories: string[] }>('/api/library/galleries/categories', init),

  getFacets: (init?: RequestInit) => apiFetch<LibraryFacets>('/api/library/galleries/facets', init),

  getGalleries: (params: GallerySearchParams = {}, init?: RequestInit) =>
    apiFetch<GalleryListResponse>(
      `/api/library/galleries${qs(params as Record<string, unknown>)}`,
      init,
    ),

  getGallery: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<Gallery>(galleryApiPath(source, sourceId), init),

  syncGallery: (source: string, sourceId: string, init?: RequestInit) =>
    apiFetch<GallerySyncResult>(galleryApiPath(source, sourceId, '/sync'), {
      ...init,
      method: 'POST',
    }),

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
    apiFetch<{ status: string; affected: number; deleted_dirs?: number; denied?: number[] }>(
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
}
