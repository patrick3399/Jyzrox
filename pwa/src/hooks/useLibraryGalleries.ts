import useSWR, { useSWRConfig } from 'swr'
import useSWRInfinite from 'swr/infinite'
import useSWRMutation from 'swr/mutation'
import { useEffect, useMemo, useRef } from 'react'
import { api } from '@/lib/api'
import { useWsJobs } from '@/lib/ws'
import type { Gallery, GalleryImage, GalleryListResponse, GallerySearchParams } from '@/lib/types'
import { isGalleryChangingJobStatus, type SwrOpts } from './galleryHookShared'

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
  return useSWR(
    ['library/galleries', params.cursor ?? params.page ?? 0, params],
    (_: unknown, { signal }: SwrOpts = {}) => api.library.getGalleries(params, { signal }),
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
    // Refresh when a job ends in any state that can change a gallery: finished
    // or partial (added/updated), cancelled or failed (the run's gallery was
    // rolled back, so its "downloading" card would otherwise linger).
    if (!isGalleryChangingJobStatus(lastJobUpdate.status)) return

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
  }, [lastJobUpdate, globalMutate])

  const {
    data,
    error,
    size,
    setSize,
    isValidating: _isValidating,
    isLoading,
    mutate,
  } = useSWRInfinite<GalleryListResponse>(
    getKey,
    ([, fetchParams]: [string, GallerySearchParams], { signal }: SwrOpts = {}) =>
      api.library.getGalleries(fetchParams, { signal }),
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
  return useSWR(
    source && sourceId ? ['library/gallery', source, sourceId] : null,
    ([, src, sid]: [string, string, string], { signal }: SwrOpts = {}) =>
      api.library.getGallery(src, sid, { signal }),
  )
}

export function useGalleryImages(source: string | null, sourceId: string | null) {
  return useSWR(
    source && sourceId ? ['gallery/images', source, sourceId] : null,
    ([, src, sid]: [string, string, string], { signal }: SwrOpts = {}) =>
      api.library.getImages(src, sid, undefined, { signal }),
  )
}

export function useInfiniteGalleryImages(
  source: string | null,
  sourceId: string | null,
  params: { limit?: number } = {},
) {
  const limit = params.limit ?? 120
  const getKey = (
    pageIndex: number,
    previousPageData: {
      images: GalleryImage[]
      has_next?: boolean
    } | null,
  ) => {
    if (!source || !sourceId) return null
    if (previousPageData && previousPageData.has_next === false) return null
    return ['gallery/images/infinite', source, sourceId, { page: pageIndex + 1, limit }]
  }

  const { data, error, size, setSize, isLoading, mutate } = useSWRInfinite(
    getKey,
    (
      [, src, sid, opts]: [string, string, string, { page: number; limit: number }],
      { signal }: SwrOpts = {},
    ) => api.library.getImages(src, sid, opts, { signal }),
    { revalidateOnFocus: false },
  )

  const images = useMemo(() => (data ? data.flatMap((page) => page.images) : []), [data])
  const favoritedImageIds = useMemo(() => {
    const set = new Set<number>()
    for (const page of data ?? []) {
      for (const id of page.favorited_image_ids ?? []) set.add(id)
    }
    return [...set]
  }, [data])
  const total = data?.[0]?.total
  const lastPage = data?.[data.length - 1]
  const isLoadingMore =
    isLoading || (size > 0 && data !== undefined && typeof data[size - 1] === 'undefined')
  const isReachingEnd =
    lastPage?.has_next === false || (total !== undefined && images.length >= total)

  return {
    data: data?.[0]
      ? { ...data[0], images, favorited_image_ids: favoritedImageIds, total }
      : undefined,
    images,
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

export function useGalleryProgress(source: string | null, sourceId: string | null) {
  return useSWR(
    source && sourceId ? ['gallery/progress', source, sourceId] : null,
    ([, src, sid]: [string, string, string], { signal }: SwrOpts = {}) =>
      api.library.getProgress(src, sid, { signal }),
  )
}

/**
 * Folds a PATCH response into the cached detail. PATCH serialises the bare
 * row: it has no `media_stats` / `source_items` and a null `cover_thumb`, so
 * those keep the values from the last GET instead of being wiped.
 */
export function mergeGalleryPatch(current: Gallery | undefined, patched: Gallery): Gallery {
  if (!current) return patched
  return {
    ...current,
    ...patched,
    cover_thumb: current.cover_thumb,
    media_stats: current.media_stats,
  }
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
          in_reading_list?: boolean
        }
      },
    ) => api.library.updateGallery(source, sourceId, arg),
    {
      // The hook owns the cache write. Callers must not mutate the detail key
      // with the response themselves: a raw write drops the GET-only fields,
      // and SWR then discards any refetch that started before it.
      populateCache: (patched: Gallery, current?: Gallery) => mergeGalleryPatch(current, patched),
      // PATCH never changes the GET-only fields, and gallery.updated over WS
      // refetches anyway.
      revalidate: false,
    },
  )
}
