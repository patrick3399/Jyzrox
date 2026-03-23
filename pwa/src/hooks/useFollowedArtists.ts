import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useFollowedArtists(params: { source?: string; limit?: number; offset?: number } = {}) {
  return useSWR(
    ['followed-artists', JSON.stringify(params)],
    () => api.artists.listFollowed(params),
  )
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
