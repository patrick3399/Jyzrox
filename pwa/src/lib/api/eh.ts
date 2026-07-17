import { apiFetch, qs } from './client'

import type {
  EhBrowseGalleryStatus,
  EhGallery,
  EhSearchResult,
  EhFavoritesResult,
  EhFavoriteState,
  EhGalleryRelationships,
  EhImageMap,
  EhSearchParams,
  EhComment,
} from '../types'

// ── E-Hentai ─────────────────────────────────────────────────────────

export const eh = {
  search: (params: EhSearchParams = {}, init?: RequestInit) =>
    apiFetch<EhSearchResult>(`/api/eh/search${qs(params as Record<string, unknown>)}`, init),

  imageSearch: (image: File, options: { similar: boolean; covers: boolean; expunged: boolean }) => {
    const body = new FormData()
    body.append('image', image)
    body.append('similar', String(options.similar))
    body.append('covers', String(options.covers))
    body.append('expunged', String(options.expunged))
    return apiFetch<EhSearchResult>('/api/eh/image-search', { method: 'POST', body })
  },

  getBrowseStatus: (gids: number[], init?: RequestInit) =>
    apiFetch<{ statuses: Record<string, EhBrowseGalleryStatus> }>(
      `/api/eh/browse-status${qs({ gids: gids.join(',') })}`,
      init,
    ),

  getGallery: (gid: number, token: string, init?: RequestInit) =>
    apiFetch<EhGallery>(`/api/eh/gallery/${gid}/${token}`, init),

  getGalleryRelationships: (gid: number, token: string, init?: RequestInit) =>
    apiFetch<EhGalleryRelationships>(`/api/eh/gallery/${gid}/${token}/relationships`, init),

  getImages: (gid: number, token: string, init?: RequestInit) =>
    apiFetch<EhImageMap>(`/api/eh/gallery/${gid}/${token}/images`, init),

  /** Lightweight: only scrapes page 0 for ~20 preview thumbnails */
  getPreviews: (gid: number, token: string, init?: RequestInit) =>
    apiFetch<{ gid: number; previews: Record<string, string> }>(
      `/api/eh/gallery/${gid}/${token}/previews`,
      init,
    ),

  /** Proxy an EH CDN thumbnail through our server */
  thumbProxyUrl: (url: string): string => `/api/eh/thumb-proxy?url=${encodeURIComponent(url)}`,

  getFavorites: (
    params: { favcat?: string; q?: string; next?: string; prev?: string } = {},
    init?: RequestInit,
  ) =>
    apiFetch<EhFavoritesResult>(`/api/eh/favorites${qs(params as Record<string, unknown>)}`, init),

  getFavoriteState: (gid: number, token: string, init?: RequestInit) =>
    apiFetch<EhFavoriteState>(`/api/eh/favorites/${gid}/${token}`, init),

  addFavorite: (gid: number, token: string, favcat?: number, note?: string) =>
    apiFetch<{ status: string }>(`/api/eh/favorites/${gid}/${token}${qs({ favcat, note })}`, {
      method: 'POST',
    }),

  removeFavorite: (gid: number, token: string) =>
    apiFetch<{ status: string }>(`/api/eh/favorites/${gid}/${token}`, {
      method: 'DELETE',
    }),

  getPopular: (init?: RequestInit) => apiFetch<EhSearchResult>('/api/eh/popular', init),

  getToplist: (params: { tl?: number; page?: number } = {}, init?: RequestInit) =>
    apiFetch<EhSearchResult>(`/api/eh/toplists${qs(params as Record<string, unknown>)}`, init),

  getComments: (gid: number, token: string, init?: RequestInit) =>
    apiFetch<{ comments: EhComment[] }>(`/api/eh/gallery/${gid}/${token}/comments`, init),

  /** Paginated image token fetch — avoids loading all tokens upfront for large galleries */
  getImagesPaginated: (
    gid: number,
    token: string,
    startPage: number = 0,
    count: number = 20,
    init?: RequestInit,
  ) =>
    apiFetch<{
      images: Array<{ page: number; token: string }>
      previews: Record<string, string>
      has_more: boolean
      total: number
    }>(
      `/api/eh/gallery/${gid}/${token}/images-paginated?start_page=${startPage}&count=${count}`,
      init,
    ),
}
