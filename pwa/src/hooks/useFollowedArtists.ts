import useSWR from 'swr'
import useSWRInfinite from 'swr/infinite'
import useSWRMutation from 'swr/mutation'
import { useMemo } from 'react'
import { api } from '@/lib/api'
import type { FollowedArtist } from '@/lib/types'

type FollowedArtistsParams = { source?: string; limit?: number; offset?: number }
type FollowedArtistsResponse = { artists: FollowedArtist[]; total: number }

export function useFollowedArtists(params: FollowedArtistsParams = {}) {
  return useSWR(
    ['followed-artists', JSON.stringify(params)],
    () => api.artists.listFollowed(params),
  )
}

export function useInfiniteFollowedArtists(params: Omit<FollowedArtistsParams, 'offset'> = {}) {
  const limit = params.limit ?? 48
  const getKey = (pageIndex: number, previousPageData: FollowedArtistsResponse | null) => {
    if (previousPageData && previousPageData.artists.length === 0) return null
    if (previousPageData && previousPageData.artists.length < limit) return null
    return ['followed-artists/infinite', { ...params, limit, offset: pageIndex * limit }]
  }

  const { data, error, size, setSize, isLoading, mutate } = useSWRInfinite<FollowedArtistsResponse>(
    getKey,
    ([, fetchParams]: [string, FollowedArtistsParams]) => api.artists.listFollowed(fetchParams),
    { revalidateOnFocus: false },
  )

  const artists = useMemo(() => (data ? data.flatMap((page) => page.artists) : []), [data])
  const total = data?.[0]?.total
  const isLoadingMore = isLoading || (size > 0 && data !== undefined && typeof data[size - 1] === 'undefined')
  const isEmpty = data?.[0]?.artists.length === 0
  const lastPage = data?.[data.length - 1]
  const isReachingEnd = isEmpty || (lastPage !== undefined && lastPage.artists.length < limit)

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

export function useFollowArtist() {
  return useSWRMutation(
    'followed-artists',
    (_key: unknown, { arg }: { arg: { source: string; artist_id: string; artist_name?: string; artist_avatar?: string; auto_download?: boolean } }) =>
      api.artists.follow(arg),
  )
}

export function useUnfollowArtist() {
  return useSWRMutation(
    'followed-artists',
    (_key: unknown, { arg }: { arg: { artistId: string; source?: string } }) =>
      api.artists.unfollow(arg.artistId, arg.source),
  )
}

export function usePatchFollow() {
  return useSWRMutation(
    'followed-artists',
    (_key: unknown, { arg }: { arg: { artistId: string; data: { auto_download?: boolean }; source?: string } }) =>
      api.artists.patchFollow(arg.artistId, arg.data, arg.source),
  )
}

export function useCheckArtistUpdates() {
  return useSWRMutation(
    'followed-artists',
    () => api.artists.checkUpdates(),
  )
}
