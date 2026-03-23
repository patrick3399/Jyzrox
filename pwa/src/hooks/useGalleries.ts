import useSWR, { useSWRConfig } from 'swr'
import useSWRInfinite from 'swr/infinite'
import useSWRMutation from 'swr/mutation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { useWsJobs } from '@/lib/ws'
import type { GalleryListResponse, GallerySearchParams, EhSearchParams } from '@/lib/types'
import type { SearchGalleriesResponse } from '@/lib/api'

// ── Library ───────────────────────────────────────────────────────────

export function useLibrarySources() {
  return useSWR('library/sources', () => api.library.getSources(), {
    revalidateOnFocus: false,
    dedupingInterval: 300_000,
  })
}

export function useGalleryCategories() {
  return useSWR('library/categories', () => api.library.getCategories(), {
    revalidateOnFocus: false,
    dedupingInterval: 300_000,
  })
}

export function useLibraryGalleries(params: GallerySearchParams = {}) {
  // Include cursor in the SWR key so each cursor page gets its own cache slot.
  // When cursor is absent the key degrades to the same shape as before.
  return useSWR(['library/galleries', params.cursor ?? params.page ?? 0, params], () =>
    api.library.getGalleries(params),
  )
}

export function useInfiniteLibraryGalleries(
  params: Omit<GallerySearchParams, 'page' | 'cursor'> = {},
) {
  const getKey = (pageIndex: number, previousPageData: GalleryListResponse | null) => {
    // First page
    if (pageIndex === 0) return ['library/galleries/infinite', { ...params, page: 0 }]
    // No more data — stop fetching
    if (previousPageData && previousPageData.galleries.length === 0) return null
    // Prefer cursor-based pagination when the backend provides it
    if (previousPageData?.next_cursor) {
      return ['library/galleries/infinite', { ...params, cursor: previousPageData.next_cursor }]
    }
    return ['library/galleries/infinite', { ...params, page: pageIndex }]
  }

  const { lastJobUpdate } = useWsJobs()
  const { mutate: globalMutate } = useSWRConfig()
  const lastFiredRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const LIBRARY_THROTTLE_MS = 2000

  useEffect(() => {
    if (!lastJobUpdate) return
    // Only refresh when a download finishes (gallery added/updated)
    if (lastJobUpdate.status !== 'done' && lastJobUpdate.status !== 'partial') return

    const now = Date.now()
    const elapsed = now - lastFiredRef.current
    const doMutate = () => {
      lastFiredRef.current = Date.now()
      // Revalidate all library/galleries cache keys
      globalMutate(
        (key: unknown) => Array.isArray(key) && key[0] === 'library/galleries/infinite',
        undefined,
        { revalidate: true },
      )
    }

    if (elapsed >= LIBRARY_THROTTLE_MS) {
      doMutate()
    } else {
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(doMutate, LIBRARY_THROTTLE_MS - elapsed)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastJobUpdate])

  const { data, error, size, setSize, isValidating, isLoading, mutate } =
    useSWRInfinite<GalleryListResponse>(
      getKey,
      ([, fetchParams]: [string, GallerySearchParams]) => api.library.getGalleries(fetchParams),
      { revalidateOnFocus: false },
    )

  const galleries = useMemo(() => (data ? data.flatMap((page) => page.galleries) : []), [data])
  const total = data?.[0]?.total
  const isLoadingMore =
    isLoading || (size > 0 && data !== undefined && typeof data[size - 1] === 'undefined')
  const isEmpty = data?.[0]?.galleries.length === 0
  const lastPage = data?.[data.length - 1]
  const isReachingEnd =
    isEmpty || (lastPage !== undefined && lastPage.galleries.length < (params.limit ?? 24))

  return {
    galleries,
    total,
    error,
    isLoading,
    isLoadingMore,
    isReachingEnd,
    size,
    setSize,
    mutate,
    loadMore: () => setSize(size + 1),
  }
}

export function useLibraryGallery(source: string | null, sourceId: string | null) {
  return useSWR(source && sourceId ? ['library/gallery', source, sourceId] : null, () =>
    api.library.getGallery(source!, sourceId!),
  )
}

export function useGalleryImages(source: string | null, sourceId: string | null) {
  return useSWR(source && sourceId ? ['gallery/images', source, sourceId] : null, () =>
    api.library.getImages(source!, sourceId!),
  )
}

export function useGalleryProgress(source: string | null, sourceId: string | null) {
  return useSWR(source && sourceId ? ['gallery/progress', source, sourceId] : null, () =>
    api.library.getProgress(source!, sourceId!),
  )
}

export function useUpdateGallery(source: string, sourceId: string) {
  return useSWRMutation(
    ['library/gallery', source, sourceId],
    (
      _key: unknown,
      {
        arg,
      }: {
        arg: {
          favorited?: boolean
          rating?: number
          title?: string
          title_jpn?: string
          category?: string
        }
      },
    ) => api.library.updateGallery(source, sourceId, arg),
  )
}

// ── E-Hentai ──────────────────────────────────────────────────────────

export function useEhSearch(params: EhSearchParams, enabled = true) {
  return useSWR(
    enabled ? ['eh/search', params] : null,
    (_: unknown, { signal }: { signal?: AbortSignal } = {}) => api.eh.search(params, { signal }),
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
    ([, g, t]: [string, number, string], { signal }: { signal?: AbortSignal } = {}) =>
      api.eh.getGallery(g, t, { signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhGalleryImages(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/images', gid, token] : null,
    ([, g, t]: [string, number, string], { signal }: { signal?: AbortSignal } = {}) =>
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
    (_: unknown, { signal }: { signal?: AbortSignal } = {}) => api.eh.getFavorites(params, { signal }),
    { revalidateOnFocus: false },
  )
}

/** Lightweight hook — only fetches first detail page for ~20 preview thumbs */
export function useEhGalleryPreviews(gid: number | null, token: string | null) {
  return useSWR(
    gid && token ? ['eh/previews', gid, token] : null,
    ([, g, t]: [string, number, string], { signal }: { signal?: AbortSignal } = {}) =>
      api.eh.getPreviews(g, t, { signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhGalleryComments(gid: number | null, token: string | null, enabled = false) {
  return useSWR(
    enabled && gid && token ? ['eh/comments', gid, token] : null,
    ([, g, t]: [string, number, string]) => api.eh.getComments(g, t),
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
  // fetchUpTo single-instance guards
  const fetchUpToTargetRef = useRef(0)
  const fetchUpToActiveRef = useRef(false)

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
    fetchUpToTargetRef.current = 0
    fetchUpToActiveRef.current = false
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
   * Skips if fetchUpTo is actively running — it will handle any needed fetches.
   */
  const onPageChange = useCallback(
    (currentPage: number) => {
      if (doneRef.current || fetchingRef.current) return
      if (fetchUpToActiveRef.current) return
      const fetchedUpTo = nextStartRef.current // already fetched count (0-indexed count = highest page index)
      if (currentPage >= fetchedUpTo - prefetchThreshold) {
        fetchNextBatch()
      }
    },
    [fetchNextBatch, prefetchThreshold],
  )

  /**
   * Imperatively ensure tokens are available up to `targetPage`.
   * Single-instance: if already running, the active loop picks up the
   * latest target via fetchUpToTargetRef instead of spawning a second loop.
   */
  const fetchUpTo = useCallback(
    async (targetPage: number) => {
      // Update target — latest/highest caller wins
      fetchUpToTargetRef.current = Math.max(fetchUpToTargetRef.current, targetPage)

      // If already running, the active loop will pick up the new target
      if (fetchUpToActiveRef.current) return
      fetchUpToActiveRef.current = true

      try {
        while (!doneRef.current && nextStartRef.current < fetchUpToTargetRef.current) {
          if (fetchingRef.current) {
            // Wait for the in-flight batch to finish before attempting the next
            await new Promise<void>((r) => setTimeout(r, 100))
            continue
          }
          await fetchNextBatch()
        }
      } finally {
        fetchUpToActiveRef.current = false
      }
    },
    [fetchNextBatch],
  )

  return {
    tokenMap,
    previewMap,
    isLoading,
    error,
    onPageChange,
    fetchUpTo,
    isDone: doneRef.current,
  }
}

// ── Unified Search ────────────────────────────────────────────────────

export function useSearchGalleries(q: string, options?: { sort?: string; limit?: number }) {
  const getKey = (pageIndex: number, previousPageData: SearchGalleriesResponse | null) => {
    if (!q) return null
    if (pageIndex === 0) return ['search/galleries', q, options]
    if (previousPageData && !previousPageData.has_next) return null
    if (previousPageData?.next_cursor) {
      return ['search/galleries', q, { ...options, cursor: previousPageData.next_cursor }]
    }
    return ['search/galleries', q, { ...options, page: pageIndex + 1 }]
  }

  const { data, error, size, setSize, isLoading } = useSWRInfinite<SearchGalleriesResponse>(
    getKey,
    ([, query, opts]: [
      string,
      string,
      { cursor?: string; page?: number; sort?: string; limit?: number } | undefined,
    ]) => api.search.galleries(query, opts),
    { revalidateOnFocus: false },
  )

  const items = useMemo(() => (data ? data.flatMap((page) => page.items) : []), [data])
  const total = data?.[0]?.total
  const lastPage = data?.[data.length - 1]
  const isReachingEnd =
    lastPage?.has_next === false ||
    (lastPage?.has_next === undefined && (lastPage?.items?.length ?? 0) < (options?.limit ?? 24))

  return {
    items,
    total,
    error,
    isLoading,
    isReachingEnd,
    size,
    setSize,
    loadMore: () => setSize(size + 1),
  }
}

export function useEhPopular(enabled = true) {
  return useSWR(
    enabled ? 'eh/popular' : null,
    (_: unknown, { signal }: { signal?: AbortSignal } = {}) => api.eh.getPopular({ signal }),
    { revalidateOnFocus: false },
  )
}

export function useEhToplist(tl: number, page = 0, enabled = true) {
  return useSWR(
    enabled ? ['eh/toplist', tl, page] : null,
    (_: unknown, { signal }: { signal?: AbortSignal } = {}) => api.eh.getToplist({ tl, page }, { signal }),
    { revalidateOnFocus: false },
  )
}
