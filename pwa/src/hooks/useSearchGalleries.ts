import { useSWRConfig } from 'swr'
import useSWRInfinite from 'swr/infinite'
import { useEffect, useMemo, useRef } from 'react'
import { api } from '@/lib/api'
import { useWsJobs } from '@/lib/ws'
import type { SearchGalleriesResponse } from '@/lib/api'
import { isGalleryChangingJobStatus } from './galleryHookShared'

// ── Unified Search ────────────────────────────────────────────────────

export function useSearchGalleries(
  q: string,
  options?: { sort?: string; limit?: number; fallbackData?: SearchGalleriesResponse[] },
) {
  const { fallbackData, ...restOptions } = options ?? {}

  const getKey = (pageIndex: number, previousPageData: SearchGalleriesResponse | null) => {
    if (!q) return null
    if (pageIndex === 0) return ['search/galleries', q, restOptions]
    if (previousPageData && !previousPageData.has_next) return null
    if (previousPageData?.next_cursor) {
      return ['search/galleries', q, { ...restOptions, cursor: previousPageData.next_cursor }]
    }
    return ['search/galleries', q, { ...restOptions, page: pageIndex + 1 }]
  }

  const { lastJobUpdate } = useWsJobs()
  const { mutate: globalMutate } = useSWRConfig()
  const lastFiredRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const SEARCH_THROTTLE_MS = 2000

  useEffect(() => {
    if (!lastJobUpdate) return
    if (!isGalleryChangingJobStatus(lastJobUpdate.status)) return

    const now = Date.now()
    const elapsed = now - lastFiredRef.current
    const doMutate = () => {
      lastFiredRef.current = Date.now()
      globalMutate(
        (key: unknown) => Array.isArray(key) && key[0] === 'search/galleries',
        undefined,
        { revalidate: true },
      )
    }

    if (elapsed >= SEARCH_THROTTLE_MS) {
      doMutate()
    } else {
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(doMutate, SEARCH_THROTTLE_MS - elapsed)
    }
  }, [lastJobUpdate, globalMutate])

  const { data, error, size, setSize, isLoading, mutate } = useSWRInfinite<SearchGalleriesResponse>(
    getKey,
    ([, query, opts]: [
      string,
      string,
      { cursor?: string; page?: number; sort?: string; limit?: number } | undefined,
    ]) => api.search.galleries(query, opts),
    {
      revalidateOnFocus: false,
      ...(fallbackData && fallbackData.length > 0
        ? { fallbackData, initialSize: fallbackData.length }
        : {}),
    },
  )

  const items = useMemo(() => (data ? data.flatMap((page) => page.items) : []), [data])
  const total = data?.[0]?.total
  const lastPage = data?.[data.length - 1]
  const isReachingEnd =
    lastPage?.has_next === false ||
    (lastPage?.has_next === undefined && (lastPage?.items?.length ?? 0) < (restOptions.limit ?? 24))

  return {
    items,
    data,
    total,
    error,
    isLoading,
    isReachingEnd,
    size,
    setSize,
    mutate,
    loadMore: () => setSize(size + 1),
  }
}
