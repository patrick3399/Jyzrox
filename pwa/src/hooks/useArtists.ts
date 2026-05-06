'use client'

import useSWR from 'swr'
import { api } from '@/lib/api'

type SwrOpts = { signal?: AbortSignal }

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
