import { describe, expect, it } from 'vitest'
import {
  ACTIVE_JOB_STATUSES,
  SUBSCRIPTION_ACTIVE_ANCHOR,
  activeSubscriptionIds,
  dashboardQueueHref,
  isActiveJob,
  sortActiveFirst,
  withActiveSubscriptionJobs,
} from '@/lib/downloadJobFilters'
import type { DownloadJob } from '@/lib/types'

type Status = DownloadJob['status']

const job = (status: Status, subscription_id?: number | null) => ({ status, subscription_id })

describe('isActiveJob', () => {
  it.each(['queued', 'running', 'paused'] as Status[])('treats %s as active', (status) => {
    expect(isActiveJob({ status })).toBe(true)
  })

  it.each(['done', 'failed', 'partial', 'cancelled'] as Status[])(
    'treats %s as not active',
    (status) => {
      expect(isActiveJob({ status })).toBe(false)
    },
  )

  it('matches the documented active status set', () => {
    expect([...ACTIVE_JOB_STATUSES]).toEqual(['queued', 'running', 'paused'])
  })
})

describe('activeSubscriptionIds', () => {
  it('collects subscription ids of active jobs only', () => {
    const ids = activeSubscriptionIds([job('running', 1), job('paused', 2), job('queued', 3)])
    expect([...ids].sort()).toEqual([1, 2, 3])
  })

  it('ignores finished jobs even when they carry a subscription id', () => {
    const ids = activeSubscriptionIds([
      job('done', 10),
      job('failed', 11),
      job('partial', 12),
      job('cancelled', 13),
      job('running', 14),
    ])
    expect([...ids]).toEqual([14])
  })

  it('ignores manual jobs (no subscription id)', () => {
    const ids = activeSubscriptionIds([job('running'), job('queued', null), job('running', 5)])
    expect([...ids]).toEqual([5])
  })

  it('counts subscription id 0 as present', () => {
    expect(activeSubscriptionIds([job('running', 0)]).has(0)).toBe(true)
  })

  it('deduplicates subscriptions with several active jobs', () => {
    const ids = activeSubscriptionIds([job('running', 7), job('queued', 7)])
    expect(ids.size).toBe(1)
  })

  it('returns an empty set for no jobs', () => {
    expect(activeSubscriptionIds([]).size).toBe(0)
  })
})

describe('sortActiveFirst', () => {
  const items = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }]

  it('moves active ids first and keeps original order inside each partition', () => {
    const sorted = sortActiveFirst(items, new Set([5, 2, 4]))
    expect(sorted.map((i) => i.id)).toEqual([2, 4, 5, 1, 3])
  })

  it('returns the original order when nothing is active', () => {
    expect(sortActiveFirst(items, new Set()).map((i) => i.id)).toEqual([1, 2, 3, 4, 5])
  })

  it('returns the original order when everything is active', () => {
    expect(sortActiveFirst(items, new Set([1, 2, 3, 4, 5])).map((i) => i.id)).toEqual([
      1, 2, 3, 4, 5,
    ])
  })

  it('ignores active ids that are not in the list', () => {
    expect(sortActiveFirst(items, new Set([99])).map((i) => i.id)).toEqual([1, 2, 3, 4, 5])
  })

  it('does not mutate the input array', () => {
    const input = [{ id: 1 }, { id: 2 }]
    const sorted = sortActiveFirst(input, new Set([2]))
    expect(sorted).not.toBe(input)
    expect(input.map((i) => i.id)).toEqual([1, 2])
  })
})

describe('dashboardQueueHref', () => {
  const ANCHOR_HREF = `/queue#${SUBSCRIPTION_ACTIVE_ANCHOR}`

  it('exposes the anchor id used by the queue page', () => {
    expect(SUBSCRIPTION_ACTIVE_ANCHOR).toBe('subscription-active')
  })

  it('links to the plain queue for an empty job list', () => {
    expect(dashboardQueueHref([])).toBe('/queue')
  })

  it('links to the plain queue when manual and subscription jobs are mixed', () => {
    expect(dashboardQueueHref([{ subscription_id: 1 }, { subscription_id: null }])).toBe('/queue')
    expect(dashboardQueueHref([{ subscription_id: 1 }, {}])).toBe('/queue')
  })

  it('links to the plain queue when all jobs are manual', () => {
    expect(dashboardQueueHref([{ subscription_id: null }, {}])).toBe('/queue')
  })

  it('links to the subscription section when every job is subscription-driven', () => {
    expect(dashboardQueueHref([{ subscription_id: 1 }, { subscription_id: 2 }])).toBe(ANCHOR_HREF)
  })

  it('treats subscription id 0 as a subscription job', () => {
    expect(dashboardQueueHref([{ subscription_id: 0 }])).toBe(ANCHOR_HREF)
  })
})

describe('withActiveSubscriptionJobs', () => {
  const full = (
    id: string,
    status: Status,
    created_at: string,
    subscription_id: number | null = 1,
  ): DownloadJob => ({
    id,
    url: 'https://example.com',
    source: 'pixiv',
    status,
    subscription_id,
    progress: {},
    error: null,
    created_at,
    finished_at: null,
    retry_count: 0,
    max_retries: 3,
    next_retry_at: null,
  })

  it('replaces a finished latest job with a newer active run of the same subscription', () => {
    // The stale latest-job fetch still shows the previous run; the card must see the new one.
    const merged = withActiveSubscriptionJobs({ 1: full('old', 'done', '2026-10-01T00:00:00Z') }, [
      full('new', 'running', '2026-10-02T00:00:00Z'),
    ])
    expect(merged[1].id).toBe('new')
  })

  it('adds an active job for a subscription with no fetched latest job', () => {
    const merged = withActiveSubscriptionJobs({}, [full('new', 'queued', '2026-10-02T00:00:00Z', 7)])
    expect(merged[7].id).toBe('new')
  })

  it('keeps the latest-job entry for the same job because it has the fresher WS status', () => {
    const merged = withActiveSubscriptionJobs({ 1: full('j', 'done', '2026-10-02T00:00:00Z') }, [
      full('j', 'running', '2026-10-02T00:00:00Z'),
    ])
    expect(merged[1].status).toBe('done')
  })

  it('keeps a newer active latest job over an older active one', () => {
    const merged = withActiveSubscriptionJobs(
      { 1: full('newer', 'running', '2026-10-03T00:00:00Z') },
      [full('older', 'queued', '2026-10-01T00:00:00Z')],
    )
    expect(merged[1].id).toBe('newer')
  })

  it('ignores non-subscription and inactive jobs', () => {
    const latest = { 1: full('old', 'done', '2026-10-01T00:00:00Z') }
    const merged = withActiveSubscriptionJobs(latest, [
      full('manual', 'running', '2026-10-02T00:00:00Z', null),
      full('finished', 'done', '2026-10-02T00:00:00Z'),
    ])
    expect(merged).toEqual(latest)
  })
})
