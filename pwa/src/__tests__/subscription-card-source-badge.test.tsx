/**
 * Feature test: the site badge leads the subscription card's first row, on the
 * same line as the name and the enable switch, with the group and
 * auto-download badges on the row below.
 *
 * Guards: the badge used to follow the name inside a wrapping row, so it moved
 * with the name's length and dropped to a second line beside the group badge.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Subscription, SubscriptionGroup } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'
import { sourceColorClass } from '@/lib/sourceStyle'
import { t } from '@/lib/i18n'

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

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

function makeSub(overrides: Partial<Subscription> = {}): Subscription {
  return {
    id: 1,
    name: 'A subscription with a very long name that would once have pushed badges down',
    url: 'https://www.pixiv.net/users/1',
    source: 'pixiv',
    source_id: '1',
    avatar_url: null,
    enabled: true,
    auto_download: true,
    cron_expr: '0 */2 * * *',
    last_checked_at: null,
    last_item_id: null,
    last_status: 'pending',
    last_error: null,
    next_check_at: null,
    created_at: null,
    last_job_id: null,
    group_id: 2,
    ...overrides,
  }
}

function renderCard(sub: Subscription) {
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
      showGroup
    />,
  )
}

describe('SubscriptionCard site badge', () => {
  it('leads a non-wrapping first row shared only with the name and the switch', () => {
    const sub = makeSub()
    renderCard(sub)
    const badge = screen.getByTestId('subscription-source-badge')
    const row = badge.parentElement as HTMLElement

    expect(row.firstElementChild).toBe(badge)
    expect(row.className).not.toContain('flex-wrap')
    expect(badge.className).toContain('shrink-0')
    expect(row.contains(screen.getByText(sub.name as string))).toBe(true)
    expect(row.contains(screen.getByRole('switch'))).toBe(true)
    expect(row.contains(screen.getByTestId('subscription-group-badge'))).toBe(false)
    expect(row.contains(screen.getByText(t('subscriptions.autoDownload')))).toBe(false)
  })

  it('uses the shared site colour', () => {
    renderCard(makeSub({ source: 'pixiv' }))
    expect(screen.getByTestId('subscription-source-badge').className).toContain(
      sourceColorClass('pixiv'),
    )
  })

  it('shows "Other" in the neutral colour when no site was detected', () => {
    renderCard(makeSub({ source: null }))
    const badge = screen.getByTestId('subscription-source-badge')
    expect(badge.textContent).toBe(t('subscriptions.sourceOther'))
    expect(badge.className).toContain(sourceColorClass(null))
  })
})
