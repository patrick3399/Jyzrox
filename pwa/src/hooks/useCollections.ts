import useSWR from 'swr'
import { api } from '@/lib/api'

export function useCollections() {
  return useSWR('collections', () => api.collections.list())
}

export function useCollection(id: number | null, params: { page?: number; limit?: number } = {}) {
  return useSWR(
    id ? ['collection', id, params.page ?? 0] : null,
    () => api.collections.get(id!, params),
    { revalidateOnFocus: false },
  )
}
