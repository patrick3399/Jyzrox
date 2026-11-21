/**
 * Feature test: the site badge sits in the card's right column, under the
 * enable switch and centred in the space above the footer, apart from the
 * name and the group / auto-download badges.
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
  it('sits under the switch in a right column of its own, centred in the space left', () => {
    const sub = makeSub()
    renderCard(sub)
    const badge = screen.getByTestId('subscription-source-badge')
    const centre = badge.parentElement as HTMLElement
    const column = centre.parentElement as HTMLElement
    const toggle = screen.getByRole('switch')

    expect(centre.className).toContain('flex-1')
    expect(centre.className).toContain('items-center')
    expect(column.className).toContain('flex-col')
    expect(column.className).toContain('shrink-0')
    expect(column.firstElementChild).toBe(toggle)
    expect(column.lastElementChild).toBe(centre)
    expect(column.contains(screen.getByText(sub.name as string))).toBe(false)
    expect(column.contains(screen.getByTestId('subscription-group-badge'))).toBe(false)
    expect(column.contains(screen.getByText(t('subscriptions.autoDownload')))).toBe(false)
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
