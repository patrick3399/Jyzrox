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
