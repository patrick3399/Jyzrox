import useSWR from 'swr'
import { api } from '@/lib/api'

export interface NavCounts {
  '/library': number
  '/subscriptions': number
  '/collections': number
}

const SWR_CONFIG = {
  refreshInterval: 30000,
  revalidateOnFocus: false,
  dedupingInterval: 10000,
  onError: () => undefined,
} as const

function useLibraryCount(enabled: boolean): number {
  const { data } = useSWR(
    enabled ? 'nav-counts/library' : null,
    () => api.library.getGalleries({ limit: 1 }),
    SWR_CONFIG,
  )
  return data?.total ?? 0
}

function useSubscriptionsCount(enabled: boolean): number {
  const { data } = useSWR(
    enabled ? 'nav-counts/subscriptions' : null,
    () => api.subscriptions.list({ enabled: true, limit: 1 }),
    SWR_CONFIG,
  )
  return data?.total ?? 0
}

function useCollectionsCount(enabled: boolean): number {
  const { data } = useSWR(
    enabled ? 'nav-counts/collections' : null,
    () => api.collections.list(),
    SWR_CONFIG,
  )
  return data?.collections.length ?? 0
}

export function useNavCounts(enabled = true): NavCounts {
  const library = useLibraryCount(enabled)
  const subscriptions = useSubscriptionsCount(enabled)
  const collections = useCollectionsCount(enabled)

  return {
    '/library': library,
    '/subscriptions': subscriptions,
    '/collections': collections,
  }
}
