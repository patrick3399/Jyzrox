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

function useLibraryCount(): number {
  const { data } = useSWR(
    'nav-counts/library',
    () => api.library.getGalleries({ limit: 1 }),
    SWR_CONFIG,
  )
  return data?.total ?? 0
}

function useSubscriptionsCount(): number {
  const { data } = useSWR(
    'nav-counts/subscriptions',
    () => api.subscriptions.list({ enabled: true, limit: 1 }),
    SWR_CONFIG,
  )
  return data?.total ?? 0
}

function useCollectionsCount(): number {
  const { data } = useSWR('nav-counts/collections', () => api.collections.list(), SWR_CONFIG)
  return data?.collections.length ?? 0
}

export function useNavCounts(): NavCounts {
  const library = useLibraryCount()
  const subscriptions = useSubscriptionsCount()
  const collections = useCollectionsCount()

  return {
    '/library': library,
    '/subscriptions': subscriptions,
    '/collections': collections,
  }
}
