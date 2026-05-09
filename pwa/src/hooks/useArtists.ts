'use client'

import useSWR from 'swr'
import useSWRInfinite from 'swr/infinite'
import { api } from '@/lib/api'
import { useMemo } from 'react'
import type { ArtistSummary } from '@/lib/types'

type SwrOpts = { signal?: AbortSignal }
type ArtistsResponse = { artists: ArtistSummary[]; total: number }

export function useArtists(
  params: {
    q?: string
    source?: string
    sort?: string
    page?: number
    limit?: number
  } = {},
) {
  const key = ['artists', JSON.stringify(params)]
  return useSWR(key, (_: unknown, { signal }: SwrOpts = {}) => api.library.getArtists(params, { signal }))
}

export function useInfiniteArtists(
  params: {
    q?: string
    source?: string
    sort?: string
    limit?: number
  } = {},
) {
  const getKey = (pageIndex: number, previousPageData: ArtistsResponse | null) => {
    if (previousPageData && previousPageData.artists.length === 0) return null
    if (previousPageData && previousPageData.artists.length < (params.limit ?? 30)) return null
    return ['artists/infinite', { ...params, page: pageIndex }]
  }

  const { data, error, size, setSize, isLoading, mutate } = useSWRInfinite<ArtistsResponse>(
    getKey,
    ([, fetchParams]: [string, Parameters<typeof api.library.getArtists>[0]], { signal }: SwrOpts = {}) =>
      api.library.getArtists(fetchParams, { signal }),
    { revalidateOnFocus: false },
  )

  const artists = useMemo(() => (data ? data.flatMap((page) => page.artists) : []), [data])
  const total = data?.[0]?.total
  const isLoadingMore = isLoading || (size > 0 && data !== undefined && typeof data[size - 1] === 'undefined')
  const isEmpty = data?.[0]?.artists.length === 0
  const lastPage = data?.[data.length - 1]
  const isReachingEnd = isEmpty || (lastPage !== undefined && lastPage.artists.length < (params.limit ?? 30))

  return {
    artists,
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

export function useArtistSummary(artistId: string) {
  return useSWR(
    artistId ? ['artist-summary', artistId] : null,
    ([, id]: [string, string], { signal }: SwrOpts = {}) => api.library.getArtistSummary(id, { signal }),
  )
}

export function useArtistImages(
  artistId: string,
  params: {
    page?: number
    limit?: number
    sort?: 'newest' | 'oldest'
  } = {},
) {
  return useSWR(
    artistId ? ['artist-images', artistId, JSON.stringify(params)] : null,
    ([, id]: [string, string, string], { signal }: SwrOpts = {}) =>
      api.library.getArtistImages(id, params, { signal }),
  )
}
