/**
 * Feature test: the subscriptions page can be laid out by site or by how long
 * ago each subscription was last checked, the choice is remembered per device, every subscription is loaded past the API page cap,
 * and a card shows its schedule group when the list is not laid out by group.
 *
 * Guards: biggest site first / "Other" last / active first; never-checked
 * first, then the longest unchecked, freshest last; unreadable storage or an
 * unknown stored value falls back to the group view; a 450-row account is not cut at 200; the group
 * badge appears only for a grouped subscription with showGroup.
 */

import { afterEach, describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Subscription, SubscriptionGroup } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'
import {
  SUBSCRIPTION_VIEW_KEY,
  groupBySource,
  groupBySyncAge,
  readSubscriptionView,
  writeSubscriptionView,
} from '@/components/subscriptions/sourceGrouping'
import { SUBSCRIPTION_PAGE_SIZE, fetchAllSubscriptions } from '@/hooks/useSubscriptions'

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

function makeSub(overrides: Partial<Subscription> = {}): Subscription {
  return {
    id: 1,
    name: 'Sub',
    url: 'https://x.com/someone',
    source: 'twitter',
    source_id: 'someone',
    avatar_url: null,
    enabled: true,
    auto_download: false,
    cron_expr: '0 */2 * * *',
    last_checked_at: null,
    last_item_id: null,
    last_status: 'pending',
    last_error: null,
    next_check_at: null,
    created_at: null,
    last_job_id: null,
    group_id: null,
    ...overrides,
  }
}

const GROUP = {
  id: 2,
  name: 'Best',
  schedule: '0 */2 * * *',
  concurrency: 2,
  enabled: true,
  priority: 0,
  is_system: false,
  status: 'idle',
  last_run_at: null,
  last_completed_at: null,
  created_at: null,
  updated_at: null,
  sub_count: 1,
} as SubscriptionGroup

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('groupBySource', () => {
  it('orders sites by size, puts unknown sources last and active downloads first', () => {
    const subs = [
      makeSub({ id: 1, source: 'weibo' }),
      makeSub({ id: 2, source: null }),
      makeSub({ id: 3, source: 'twitter' }),
      makeSub({ id: 4, source: 'twitter' }),
      makeSub({ id: 5, source: 'instagram' }),
      makeSub({ id: 6, source: 'instagram' }),
      makeSub({ id: 7, source: 'twitter' }),
    ]

    const sections = groupBySource(subs, new Set([7]))

    expect(sections.map((s) => s.source)).toEqual(['twitter', 'instagram', 'weibo', null])
    expect(sections[0].subs.map((s) => s.id)).toEqual([7, 3, 4])
  })
})

describe('groupBySyncAge', () => {
  const NOW = Date.parse('2026-10-27T12:00:00Z')
  const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString()

  it('puts never-checked first, then the longest unchecked, freshest last, hiding empty buckets', () => {
    const subs = [
      makeSub({ id: 1, last_checked_at: hoursAgo(2) }),
      makeSub({ id: 2, last_checked_at: hoursAgo(20 * 24) }),
      makeSub({ id: 3, last_checked_at: null }),
      makeSub({ id: 4, last_checked_at: hoursAgo(5 * 24) }),
      makeSub({ id: 5, last_checked_at: hoursAgo(15 * 24) }),
      makeSub({ id: 6, last_checked_at: hoursAgo(10 * 24) }),
      makeSub({ id: 7, last_checked_at: hoursAgo(30) }),
    ]

    const sections = groupBySyncAge(subs, new Set(), NOW)

    expect(sections.map((s) => s.bucket)).toEqual([
      'never',
      'over14d',
      'days7to14',
      'days3to7',
      'days1to3',
      'within24h',
    ])
    // Oldest check first inside a bucket.
    expect(sections[1].subs.map((s) => s.id)).toEqual([2, 5])

    const withoutMiddle = groupBySyncAge(
      subs.filter((s) => s.id !== 6),
      new Set(),
      NOW,
    )
    expect(withoutMiddle.map((s) => s.bucket)).not.toContain('days7to14')
  })

  it('splits at the 24-hour and 14-day boundaries', () => {
    const sections = groupBySyncAge(
      [
        makeSub({ id: 1, last_checked_at: hoursAgo(23) }),
        makeSub({ id: 2, last_checked_at: hoursAgo(25) }),
        makeSub({ id: 3, last_checked_at: hoursAgo(14 * 24 - 1) }),
        makeSub({ id: 4, last_checked_at: hoursAgo(14 * 24 + 1) }),
      ],
      new Set(),
      NOW,
    )
    const bucketOf = (id: number) =>
      sections.find((s) => s.subs.some((sub) => sub.id === id))?.bucket
    expect(bucketOf(1)).toBe('within24h')
    expect(bucketOf(2)).toBe('days1to3')
    expect(bucketOf(3)).toBe('days7to14')
    expect(bucketOf(4)).toBe('over14d')
  })

  it('orders never-checked subscriptions by creation, oldest first, with unknown creation last', () => {
    const sections = groupBySyncAge(
      [
        makeSub({ id: 1, created_at: '2026-10-20T00:00:00Z' }),
        makeSub({ id: 2, created_at: null }),
        makeSub({ id: 3, created_at: '2026-10-07T00:00:00Z' }),
      ],
      new Set(),
      NOW,
    )
    expect(sections).toHaveLength(1)
    expect(sections[0].subs.map((s) => s.id)).toEqual([3, 1, 2])
  })

  it('treats an unparseable check time as never checked instead of fresh', () => {
    const sections = groupBySyncAge(
      [makeSub({ id: 1, last_checked_at: 'not-a-date' })],
      new Set(),
      NOW,
    )
    expect(sections.map((s) => s.bucket)).toEqual(['never'])
  })

  it('leads each bucket with active downloads', () => {
    const sections = groupBySyncAge(
      [
        makeSub({ id: 1, last_checked_at: hoursAgo(50) }),
        makeSub({ id: 2, last_checked_at: hoursAgo(30) }),
      ],
      new Set([2]),
      NOW,
    )
    expect(sections[0].subs.map((s) => s.id)).toEqual([2, 1])
  })
})

describe('subscription view preference', () => {
  it('round-trips the site view through localStorage', () => {
    expect(readSubscriptionView()).toBe('group')
    writeSubscriptionView('source')
    expect(localStorage.getItem(SUBSCRIPTION_VIEW_KEY)).toBe('source')
    expect(readSubscriptionView()).toBe('source')
  })

  it('round-trips the sync-age view and ignores an unknown stored value', () => {
    writeSubscriptionView('time')
    expect(readSubscriptionView()).toBe('time')
    localStorage.setItem(SUBSCRIPTION_VIEW_KEY, 'bogus')
    expect(readSubscriptionView()).toBe('group')
  })

  it('falls back to the group view when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readSubscriptionView()).toBe('group')
    expect(() => writeSubscriptionView('source')).not.toThrow()
  })
})

describe('fetchAllSubscriptions', () => {
  it('loads every page instead of stopping at the API page cap', async () => {
    const all = Array.from({ length: 450 }, (_, i) => makeSub({ id: i + 1 }))
    const listPage = vi.fn(
      async ({ limit = 50, offset = 0 }: { limit?: number; offset?: number } = {}) => ({
        subscriptions: all.slice(offset, offset + limit),
        total: all.length,
      }),
    )

    const result = await fetchAllSubscriptions(listPage)

    expect(result.subscriptions).toHaveLength(450)
    expect(result.total).toBe(450)
    expect(listPage).toHaveBeenCalledTimes(3)
    expect(listPage).toHaveBeenNthCalledWith(3, { limit: SUBSCRIPTION_PAGE_SIZE, offset: 400 })
  })

  it('drops a row repeated across pages when the offsets shift mid-fetch', async () => {
    const first = Array.from({ length: SUBSCRIPTION_PAGE_SIZE }, (_, i) => makeSub({ id: i + 1 }))
    const listPage = vi
      .fn()
      .mockResolvedValueOnce({ subscriptions: first, total: 201 })
      // A new subscription pushed row 200 onto the second page.
      .mockResolvedValueOnce({ subscriptions: [first[199], makeSub({ id: 999 })], total: 202 })

    const result = await fetchAllSubscriptions(listPage)

    expect(result.subscriptions.map((s) => s.id)).toHaveLength(201)
    expect(new Set(result.subscriptions.map((s) => s.id)).size).toBe(201)
  })
})

describe('SubscriptionCard group badge', () => {
  function renderCard(sub: Subscription, showGroup: boolean) {
    const noop = vi.fn()
    render(
      <SubscriptionCard
        sub={sub}
        latestJob={null}
        groups={[GROUP]}
        onToggle={noop}
        onCheck={noop}
        onBackfill={noop}
        onDelete={noop}
        onAutoDownloadToggle={noop}
        onMoveToGroup={noop}
        onRename={noop}
        checkingId={null}
        showGroup={showGroup}
      />,
    )
  }

  it('shows the group name and schedule of a grouped subscription in the site view', () => {
    renderCard(makeSub({ group_id: 2 }), true)
    const badge = screen.getByTestId('subscription-group-badge')
    expect(badge.textContent).toContain('Best')
    expect(badge.textContent).toContain('0 */2 * * *')
  })

  it('shows no badge for an ungrouped subscription', () => {
    renderCard(makeSub({ group_id: null }), true)
    expect(screen.queryByTestId('subscription-group-badge')).toBeNull()
  })

  it('shows no badge when the list is already laid out by group', () => {
    renderCard(makeSub({ group_id: 2 }), false)
    expect(screen.queryByTestId('subscription-group-badge')).toBeNull()
  })
})
