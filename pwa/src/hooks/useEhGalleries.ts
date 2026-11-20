import useSWR from 'swr'
import { api } from '@/lib/api'
import type { EhSearchParams } from '@/lib/types'
import type { SwrOpts } from './galleryHookShared'

// ── E-Hentai ──────────────────────────────────────────────────────────

export function useEhSearch(params: EhSearchParams, enabled = true) {
  return useSWR(
    enabled ? ['eh/search', params] : null,
    (_: unknown, { signal }: SwrOpts = {}) => api.eh.search(params, { signal }),
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 60000,
    },
  )
}

export function useEhGallery(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/gallery', gid, token] : null,
    ([, g, t]: [string, number, string], { signal }: SwrOpts = {}) =>
      api.eh.getGallery(g, t, { signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhGalleryImages(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/images', gid, token] : null,
    ([, g, t]: [string, number, string], { signal }: SwrOpts = {}) =>
      api.eh.getImages(g, t, { signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhFavorites(
  params: { favcat?: string; q?: string; next?: string; prev?: string },
  enabled = true,
) {
  return useSWR(
    enabled ? ['eh/favorites', params] : null,
    (_: unknown, { signal }: SwrOpts = {}) => api.eh.getFavorites(params, { signal }),
    { revalidateOnFocus: false },
  )
}

/** Lightweight hook — only fetches first detail page for ~20 preview thumbs */
export function useEhGalleryPreviews(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/previews', gid, token] : null,
    ([, g, t]: [string, number, string], { signal }: SwrOpts = {}) =>
      api.eh.getPreviews(g, t, { signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhGalleryComments(gid: number | null, token: string | null, enabled = false) {
  return useSWR(
    enabled && gid && token ? ['eh/comments', gid, token] : null,
    ([, g, t]: [string, number, string], { signal }: SwrOpts = {}) =>
      api.eh.getComments(g, t, { signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhPopular(enabled = true) {
  return useSWR(
    enabled ? 'eh/popular' : null,
    (_: unknown, { signal }: SwrOpts = {}) => api.eh.getPopular({ signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhToplist(tl: number, page = 0, enabled = true) {
  return useSWR(
    enabled ? ['eh/toplist', tl, page] : null,
    (_: unknown, { signal }: SwrOpts = {}) => api.eh.getToplist({ tl, page }, { signal }),
    { revalidateOnFocus: false },
  )
}
