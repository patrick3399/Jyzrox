import { t } from '@/lib/i18n'
import { sortActiveFirst } from '@/lib/downloadJobFilters'
import type { Subscription } from '@/lib/types'

/** How the subscriptions page lays out its list: by schedule group or by site. */
export type SubscriptionView = 'group' | 'source'

export const SUBSCRIPTION_VIEW_KEY = 'subscriptions_view'

// Device-only convenience: storage may be unavailable (private mode, blocked site data).
export function readSubscriptionView(): SubscriptionView {
  try {
    return localStorage.getItem(SUBSCRIPTION_VIEW_KEY) === 'source' ? 'source' : 'group'
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
