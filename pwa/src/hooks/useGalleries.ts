import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { useCallback, useEffect, useRef, useState } from 'react'
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

/**
 * Paginated EH image token loader.
 *
 * - Starts by fetching the first `batchSize` tokens immediately.
 * - When the user reaches within `prefetchThreshold` pages of the last
 *   fetched page, the next batch is fetched automatically.
 * - Returns `{ tokens, totalPages, isLoading, fetchUpTo }` so the caller
 *   can also imperatively trigger a fetch (e.g., on seek to a far page).
 */
export function useEhGalleryImagesPaginated(
  gid: number | null,
  token: string | null,
  totalPages: number,
  batchSize = 20,
  prefetchThreshold = 5,
) {
  // Map of page (1-indexed) -> pToken string
  const [tokenMap, setTokenMap] = useState<Record<number, string>>({})
  // Map of page (string key) -> preview URL or sprite string "url|ox|w|h"
  const [previewMap, setPreviewMap] = useState<Record<string, string>>({})
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  // startPage for next batch to fetch (0-indexed as the API expects)
  const nextStartRef = useRef(0)
  // Whether all pages have been fetched
  const doneRef = useRef(false)
  // In-flight guard
  const fetchingRef = useRef(false)
  // Mounted guard
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // Reset when gid/token changes
  useEffect(() => {
    setTokenMap({})
    setPreviewMap({})
    setError(null)
    nextStartRef.current = 0
    doneRef.current = false
    fetchingRef.current = false
  }, [gid, token])

  const fetchNextBatch = useCallback(async () => {
    if (!gid || !token) return
    if (doneRef.current || fetchingRef.current) return

    fetchingRef.current = true
    if (mountedRef.current) setIsLoading(true)

    try {
      const result = await api.eh.getImagesPaginated(gid, token, nextStartRef.current, batchSize)
      if (!mountedRef.current) return

      setTokenMap((prev) => {
        const next = { ...prev }
        for (const item of result.images) {
          next[item.page] = item.token
        }
        return next
      })

      if (result.previews && Object.keys(result.previews).length > 0) {
        setPreviewMap((prev) => ({ ...prev, ...result.previews }))
      }

      nextStartRef.current += result.images.length
      if (!result.has_more || nextStartRef.current >= totalPages) {
        doneRef.current = true
      }
    } catch (err) {
      if (mountedRef.current) setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      fetchingRef.current = false
      if (mountedRef.current) setIsLoading(false)
    }
  }, [gid, token, batchSize, totalPages])

  // Initial fetch
  useEffect(() => {
    if (gid && token && totalPages > 0) {
      fetchNextBatch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gid, token, totalPages])

  /**
   * Called by the reader when the current page changes.
   * Triggers the next batch fetch when within `prefetchThreshold` pages
   * of the last fetched page.
   */
  const onPageChange = useCallback(
    (currentPage: number) => {
      if (doneRef.current || fetchingRef.current) return
      const fetchedUpTo = nextStartRef.current // already fetched count (0-indexed count = highest page index)
      if (currentPage >= fetchedUpTo - prefetchThreshold) {
        fetchNextBatch()
      }
    },
    [fetchNextBatch, prefetchThreshold],
  )

  /**
   * Imperatively ensure tokens are available up to `targetPage`.
   * Used when user seeks far ahead (e.g., taps a thumbnail for page 50
   * but only 20 tokens are loaded). Fetches batches until targetPage
   * is covered or the gallery is exhausted.
   */
  const fetchUpTo = useCallback(
    async (targetPage: number) => {
      while (!doneRef.current && nextStartRef.current < targetPage) {
        await fetchNextBatch()
      }
    },
    [fetchNextBatch],
  )

  return { tokenMap, previewMap, isLoading, error, onPageChange, fetchUpTo, isDone: doneRef.current }
}

export function useEhPopular() {
  return useSWR('eh/popular', () => api.eh.getPopular(), { revalidateOnFocus: false })
}

export function useEhToplist(tl: number, page = 0) {
  return useSWR(['eh/toplist', tl, page], () => api.eh.getToplist({ tl, page }), {
    revalidateOnFocus: false,
  })
}
