import type { DownloadJob, Subscription } from '@/lib/types'

export function matchesSubscriptionSearch(
  sub: Subscription,
  latestJob: DownloadJob | null | undefined,
  query: string,
): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [sub.name, sub.url, sub.source, sub.gallery_title, latestJob?.gallery_title].some(
    (v) => typeof v === 'string' && v.toLowerCase().includes(q),
  )
}
