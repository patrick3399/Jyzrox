import useSWRInfinite from 'swr/infinite'
import { useMemo } from 'react'
import { api } from '@/lib/api'
import type { ImageBrowserResponse } from '@/lib/types'

interface UseImageBrowserParams {
  tags?: string[]
  exclude_tags?: string[]
  sort?: 'newest' | 'oldest'
  gallery_id?: number
  source?: string
  limit?: number
  jumpAt?: string
}

export function useImageBrowser(params: UseImageBrowserParams = {}) {
  const { jumpAt, ...restParams } = params

  const getKey = (pageIndex: number, previousPageData: ImageBrowserResponse | null) => {
    if (pageIndex === 0) {
      return ['library/images', { ...restParams, ...(jumpAt ? { jump_at: jumpAt } : {}) }]
    }
    if (previousPageData && !previousPageData.has_next) return null
    if (previousPageData?.next_cursor) {
      return ['library/images', { ...restParams, cursor: previousPageData.next_cursor }]
    }
    return null
  }

  const { data, error, size, setSize, isLoading } = useSWRInfinite<ImageBrowserResponse>(
    getKey,
    ([, fetchParams]: [string, UseImageBrowserParams & { cursor?: string; jump_at?: string }]) =>
      api.library.browseImages(fetchParams),
    { revalidateOnFocus: false },
  )

  const images = useMemo(
    () => (data ? data.flatMap((page) => page.images) : []),
    [data],
  )
  const isLoadingMore = isLoading || (size > 0 && data !== undefined && typeof data[size - 1] === 'undefined')
  const isEmpty = data?.[0]?.images.length === 0
  const lastPage = data?.[data.length - 1]
  const isReachingEnd = isEmpty || (lastPage !== undefined && !lastPage.has_next)

  return {
    images,
    error,
    isLoading,
    isLoadingMore,
    isReachingEnd,
    size,
    setSize,
    loadMore: () => setSize(size + 1),
  }
}
