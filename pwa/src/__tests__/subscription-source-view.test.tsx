/**
 * Feature test: the subscriptions page can be laid out by site, the choice is
 * remembered per device, every subscription is loaded past the API page cap,
 * and a card shows its schedule group when the list is not laid out by group.
 *
 * Guards: biggest site first / "Other" last / active first; unreadable storage
 * falls back to the group view; a 450-row account is not cut at 200; the group
 * badge appears only for a grouped subscription with showGroup.
 */

import { afterEach, describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Subscription, SubscriptionGroup } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'
import {
  SUBSCRIPTION_VIEW_KEY,
  groupBySource,
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

describe('subscription view preference', () => {
  it('round-trips the site view through localStorage', () => {
    expect(readSubscriptionView()).toBe('group')
    writeSubscriptionView('source')
    expect(localStorage.getItem(SUBSCRIPTION_VIEW_KEY)).toBe('source')
    expect(readSubscriptionView()).toBe('source')
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
