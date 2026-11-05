import useSWR from 'swr'
import { api } from '@/lib/api'

/** Per-user Source / Category option lists with gallery counts for the Library filters. */
export function useLibraryFacets() {
  return useSWR('library/facets', () => api.library.getFacets(), {
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  })
}
