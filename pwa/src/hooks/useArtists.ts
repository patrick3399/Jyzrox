'use client'

import useSWR from 'swr'
import { api } from '@/lib/api'

export function useArtists(params: {
  q?: string
  source?: string
  sort?: string
  page?: number
  limit?: number
} = {}) {
  const key = ['artists', JSON.stringify(params)]
  return useSWR(key, () => api.library.getArtists(params))
}

export function useArtistSummary(artistId: string) {
  return useSWR(
    artistId ? ['artist-summary', artistId] : null,
    () => api.library.getArtistSummary(artistId),
  )
}

export function useArtistImages(artistId: string, params: {
  page?: number
  limit?: number
  sort?: 'newest' | 'oldest'
} = {}) {
  return useSWR(
    artistId ? ['artist-images', artistId, JSON.stringify(params)] : null,
    () => api.library.getArtistImages(artistId, params),
  )
}
