/**
 * Feature test: the check interval of an existing subscription is visible and
 * editable on its card, and a grouped subscription shows its group's schedule
 * instead of its own (inert) cron_expr.
 *
 * Guards: ungrouped → editable cron committed through onCronChange; grouped →
 * read-only group schedule and no editor; unchanged / empty draft → no call.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { Subscription, SubscriptionGroup } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

function makeSub(overrides: Partial<Subscription> = {}): Subscription {
  return {
    id: 1,
    name: 'Sub',
    url: 'https://www.pixiv.net/users/12345',
    source: 'pixiv',
    source_id: '12345',
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

const GROUP: SubscriptionGroup = {
  id: 7,
  name: 'Nightly',
  schedule: '0 3 * * *',
  concurrency: 2,
  enabled: true,
  priority: 5,
  is_system: false,
  status: 'idle',
  last_run_at: null,
  last_completed_at: null,
  created_at: null,
  updated_at: null,
  sub_count: 1,
} as SubscriptionGroup

function renderCard(
  sub: Subscription,
  opts: {
    groups?: SubscriptionGroup[]
    onCronChange?: (sub: Subscription, cron: string) => void
  } = {},
) {
  const noop = vi.fn()
  render(
    <SubscriptionCard
      sub={sub}
      latestJob={null}
      groups={opts.groups ?? []}
      onToggle={noop}
      onCheck={noop}
      onBackfill={noop}
      onDelete={noop}
      onAutoDownloadToggle={noop}
      onMoveToGroup={noop}
      onRename={noop}
      onCronChange={opts.onCronChange}
      checkingId={null}
    />,
  )
}

describe('SubscriptionCard check interval', () => {
  it('shows the own cron_expr of an ungrouped subscription', () => {
    renderCard(makeSub({ cron_expr: '0 */6 * * *' }), { onCronChange: vi.fn() })
    expect(screen.getByTestId('subscription-interval').textContent).toContain('0 */6 * * *')
  })

  it('commits an edited cron_expr through onCronChange', () => {
    const onCronChange = vi.fn()
    const sub = makeSub()
    renderCard(sub, { onCronChange })

    fireEvent.click(screen.getByText('0 */2 * * *'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '0 0 * * 1' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onCronChange).toHaveBeenCalledTimes(1)
    expect(onCronChange).toHaveBeenCalledWith(sub, '0 0 * * 1')
  })

  it('applies a preset only after it is saved', () => {
    const onCronChange = vi.fn()
    const sub = makeSub()
    renderCard(sub, { onCronChange })

    fireEvent.click(screen.getByText('0 */2 * * *'))
    fireEvent.click(screen.getByText('1d'))
    expect(onCronChange).not.toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText('Save'))
    expect(onCronChange).toHaveBeenCalledWith(sub, '0 0 * * *')
  })

  it('does not call onCronChange when the value is unchanged or Escape is pressed', () => {
    const onCronChange = vi.fn()
    renderCard(makeSub(), { onCronChange })

    fireEvent.click(screen.getByText('0 */2 * * *'))
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
    expect(onCronChange).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('0 */2 * * *'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '0 0 * * *' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onCronChange).not.toHaveBeenCalled()
  })

  it('shows the group schedule, not the own cron_expr, for a grouped subscription', () => {
    renderCard(makeSub({ group_id: 7, cron_expr: '0 */2 * * *' }), {
      groups: [GROUP],
      onCronChange: vi.fn(),
    })
    const row = screen.getByTestId('subscription-interval').textContent ?? ''
    expect(row).toContain('Nightly')
    expect(row).toContain('0 3 * * *')
    expect(row).not.toContain('0 */2 * * *')
  })

  it('offers no editor for a grouped subscription', () => {
    renderCard(makeSub({ group_id: 7 }), { groups: [GROUP], onCronChange: vi.fn() })
    expect(screen.getByTestId('subscription-interval').querySelector('button')).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull()
  })
})
