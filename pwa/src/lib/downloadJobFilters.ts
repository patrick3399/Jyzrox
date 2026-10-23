import type { DownloadJob } from '@/lib/types'

/** Statuses that count as "in flight" (same set as the backend duplicate guard). */
export const ACTIVE_JOB_STATUSES = ['queued', 'running', 'paused'] as const

/** DOM id / URL hash (without '#') of the queue page's subscription-active section. */
export const SUBSCRIPTION_ACTIVE_ANCHOR = 'subscription-active'

export function isActiveJob(job: Pick<DownloadJob, 'status'>): boolean {
  return (ACTIVE_JOB_STATUSES as readonly string[]).includes(job.status)
}

/** Subscription ids that currently have at least one active job. */
export function activeSubscriptionIds(
  jobs: Pick<DownloadJob, 'status' | 'subscription_id'>[],
): Set<number> {
  const ids = new Set<number>()
  for (const job of jobs) {
    if (job.subscription_id != null && isActiveJob(job)) {
      ids.add(job.subscription_id)
    }
  }
  return ids
}

/** Stable partition: items whose id is active first, original order otherwise. */
export function sortActiveFirst<T extends { id: number }>(items: T[], activeIds: Set<number>): T[] {
  const active: T[] = []
  const rest: T[] = []
  for (const item of items) {
    if (activeIds.has(item.id)) active.push(item)
    else rest.push(item)
  }
  return [...active, ...rest]
}

/** Dashboard "View all" target: jump to the subscription section when every job is subscription-driven. */
export function dashboardQueueHref(jobs: Pick<DownloadJob, 'subscription_id'>[]): string {
  if (jobs.length > 0 && jobs.every((job) => job.subscription_id != null)) {
    return `/queue#${SUBSCRIPTION_ACTIVE_ANCHOR}`
  }
  return '/queue'
}
