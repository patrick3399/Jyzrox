import useSWR from 'swr'
import { api } from '@/lib/api'

/**
 * Fetches Chinese translations for a list of tags.
 * Tags should be in "namespace:name" format.
 * Returns a Record<string, string> mapping tag → translation.
 * Cached indefinitely (no revalidation).
 */
export function useTagTranslations(tags: string[]) {
  const key = tags.length > 0 ? ['tags/translations', tags.slice().sort().join(',')] : null
  return useSWR(
    key,
    () => api.tags.getTranslations(tags),
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 86400_000, // 24h
    },
  )
}
