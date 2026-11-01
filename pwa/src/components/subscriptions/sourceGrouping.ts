import { t } from '@/lib/i18n'
import { sortActiveFirst } from '@/lib/downloadJobFilters'
import type { Subscription } from '@/lib/types'

/** How the subscriptions page lays out its list: by schedule group, by site, or by last check. */
export type SubscriptionView = 'group' | 'source' | 'time'

export const SUBSCRIPTION_VIEW_KEY = 'subscriptions_view'

// Device-only convenience: storage may be unavailable (private mode, blocked site data).
export function readSubscriptionView(): SubscriptionView {
  try {
    const stored = localStorage.getItem(SUBSCRIPTION_VIEW_KEY)
    return stored === 'source' || stored === 'time' ? stored : 'group'
  } catch {
    return 'group'
  }
}

export function writeSubscriptionView(view: SubscriptionView): void {
  try {
    localStorage.setItem(SUBSCRIPTION_VIEW_KEY, view)
  } catch {
    // Not persisted; the choice still applies for this visit.
  }
}

const SOURCE_LABELS: Record<string, string> = {
  pixiv: 'Pixiv',
  twitter: 'Twitter',
  ehentai: 'E-Hentai',
  weibo: 'Weibo',
  instagram: 'Instagram',
  facebook: 'Facebook',
}

/** Display name of a subscription source; unknown (null) sources read as "Other". */
export function sourceLabel(source: string | null): string {
  if (!source) return t('subscriptions.sourceOther')
  return SOURCE_LABELS[source] ?? source
}

export interface SourceSection {
  source: string | null
  subs: Subscription[]
}

/**
 * Split subscriptions into one section per site: biggest site first, ties by
 * name, "Other" (no detected source) last. Active downloads lead each section.
 */
export function groupBySource(subs: Subscription[], activeIds: Set<number>): SourceSection[] {
  const bySource = new Map<string | null, Subscription[]>()
  for (const sub of subs) {
    const key = sub.source || null
    const list = bySource.get(key)
    if (list) list.push(sub)
    else bySource.set(key, [sub])
  }
  return [...bySource.entries()]
    .map(([source, list]) => ({ source, subs: sortActiveFirst(list, activeIds) }))
    .sort((a, b) => {
      if (a.source === null) return 1
      if (b.source === null) return -1
      return (
        b.subs.length - a.subs.length || sourceLabel(a.source).localeCompare(sourceLabel(b.source))
      )
    })
}

/** How long ago a subscription was last checked, stalest first. */
export type SyncAgeBucket =
  'never' | 'over14d' | 'days7to14' | 'days3to7' | 'days1to3' | 'within24h'

const SYNC_AGE_ORDER: SyncAgeBucket[] = [
  'never',
  'over14d',
  'days7to14',
  'days3to7',
  'days1to3',
  'within24h',
]

const DAY_MS = 86_400_000

export function syncAgeLabel(bucket: SyncAgeBucket): string {
  return t(`subscriptions.syncAge.${bucket}`)
}

function syncAgeBucket(checkedAt: number, now: number): SyncAgeBucket {
  if (Number.isNaN(checkedAt)) return 'never'
  const age = now - checkedAt
  if (age > 14 * DAY_MS) return 'over14d'
  if (age > 7 * DAY_MS) return 'days7to14'
  if (age > 3 * DAY_MS) return 'days3to7'
  if (age > DAY_MS) return 'days1to3'
  return 'within24h'
}

export interface SyncAgeSection {
  bucket: SyncAgeBucket
  subs: Subscription[]
}

/**
 * Split subscriptions by how long ago they were last checked: never checked
 * first (oldest subscription first), then the stalest check first, freshest
 * last. Empty buckets are dropped. Active downloads lead each section.
 */
export function groupBySyncAge(
  subs: Subscription[],
  activeIds: Set<number>,
  now: number = Date.now(),
): SyncAgeSection[] {
  const byBucket = new Map<SyncAgeBucket, { sub: Subscription; key: number }[]>()
  for (const sub of subs) {
    // An unparseable time reads as NaN, which lands in "never" rather than looking fresh.
    const checkedAt = sub.last_checked_at ? Date.parse(sub.last_checked_at) : NaN
    const bucket = syncAgeBucket(checkedAt, now)
    // Never-checked rows sort by creation; unknown creation goes last.
    const created = sub.created_at ? Date.parse(sub.created_at) : NaN
    const key = bucket === 'never' ? (Number.isNaN(created) ? Infinity : created) : checkedAt
    const list = byBucket.get(bucket)
    if (list) list.push({ sub, key })
    else byBucket.set(bucket, [{ sub, key }])
  }
  return SYNC_AGE_ORDER.flatMap((bucket) => {
    const list = byBucket.get(bucket)
    if (!list) return []
    list.sort((a, b) => (a.key === b.key ? a.sub.id - b.sub.id : a.key < b.key ? -1 : 1))
    return [
      {
        bucket,
        subs: sortActiveFirst(
          list.map((row) => row.sub),
          activeIds,
        ),
      },
    ]
  })
}
