import useSWR from 'swr'
import { api } from '@/lib/api'

export function useCategoryRegistry() {
  return useSWR('gallery-categories', () => api.galleryCategories.list(), {
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  })
}
