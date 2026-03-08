import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'
import type { GallerySearchParams, EhSearchParams } from '@/lib/types'

// ── Library ───────────────────────────────────────────────────────────

export function useLibraryGalleries(params: GallerySearchParams = {}) {
  // Include cursor in the SWR key so each cursor page gets its own cache slot.
  // When cursor is absent the key degrades to the same shape as before.
  return useSWR(['library/galleries', params.cursor ?? params.page ?? 0, params], () =>
    api.library.getGalleries(params),
  )
}

export function useLibraryGallery(id: number | null) {
  return useSWR(id ? ['library/gallery', id] : null, () => api.library.getGallery(id!))
}

export function useGalleryImages(id: number | null) {
  return useSWR(id ? ['gallery/images', id] : null, () => api.library.getImages(id!))
}

export function useGalleryProgress(id: number | null) {
  return useSWR(id ? ['gallery/progress', id] : null, () => api.library.getProgress(id!))
}

export function useUpdateGallery(id: number) {
  return useSWRMutation(
    ['library/gallery', id],
    (_key: unknown, { arg }: { arg: { favorited?: boolean; rating?: number } }) =>
      api.library.updateGallery(id, arg),
  )
}

// ── E-Hentai ──────────────────────────────────────────────────────────

export function useEhSearch(params: EhSearchParams) {
  // Always fire — empty params = EH homepage (like EhViewer default behaviour)
  return useSWR(['eh/search', params], () => api.eh.search(params), { revalidateOnFocus: false })
}

export function useEhGallery(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/gallery', gid, token] : null,
    () => api.eh.getGallery(gid!, token!),
    { revalidateOnFocus: false },
  )
}

export function useEhGalleryImages(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/images', gid, token] : null,
    () => api.eh.getImages(gid!, token!),
    { revalidateOnFocus: false },
  )
}

export function useEhFavorites(
  params: { favcat?: string; q?: string; next?: string; prev?: string },
  enabled = true,
) {
  return useSWR(enabled ? ['eh/favorites', params] : null, () => api.eh.getFavorites(params), {
    revalidateOnFocus: false,
  })
}

/** Lightweight hook — only fetches first detail page for ~20 preview thumbs */
export function useEhGalleryPreviews(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/previews', gid, token] : null,
    () => api.eh.getPreviews(gid!, token!),
    { revalidateOnFocus: false },
  )
}
