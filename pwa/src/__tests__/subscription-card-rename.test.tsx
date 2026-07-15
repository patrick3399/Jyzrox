/**
 * Feature test: subscription name is editable after creation via inline
 * click-to-edit, mirroring the Gallery title rename UX.
 *
 * Guards the wiring that the name display becomes an <input> on click,
 * commits the trimmed value through onRename on blur / Enter, and does
 * NOT fire onRename when the value is unchanged or on Escape.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { Subscription } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'

// next/link renders a plain anchor in tests
vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

function makeSub(overrides: Partial<Subscription> = {}): Subscription {
  return {
    id: 1,
    name: 'Old Name',
    url: 'https://www.pixiv.net/users/12345',
    source: 'pixiv',
    source_id: '12345',
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
    group_id: null,
    ...overrides,
  }
}

function renderCard(sub: Subscription, onRename = vi.fn()) {
  const noop = vi.fn()
  render(
    <SubscriptionCard
      sub={sub}
      latestJob={null}
      groups={[]}
      onToggle={noop}
      onCheck={noop}
      onBackfill={noop}
      onDelete={noop}
      onAutoDownloadToggle={noop}
      onMoveToGroup={noop}
      onRename={onRename}
      checkingId={null}
    />,
  )
  return { onRename }
}

describe('SubscriptionCard inline rename', () => {
  it('commits a trimmed new name through onRename on blur', () => {
    const { onRename } = renderCard(makeSub())

    fireEvent.click(screen.getByText('Old Name'))
    const input = screen.getByDisplayValue('Old Name') as HTMLInputElement
    fireEvent.change(input, { target: { value: '  New Name  ' } })
    fireEvent.blur(input)

    expect(onRename).toHaveBeenCalledTimes(1)
    expect(onRename).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), 'New Name')
  })

  it('commits on Enter key', () => {
    const { onRename } = renderCard(makeSub())

    fireEvent.click(screen.getByText('Old Name'))
    const input = screen.getByDisplayValue('Old Name') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Renamed' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onRename).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), 'Renamed')
  })

  it('does not fire onRename when the value is unchanged', () => {
    const { onRename } = renderCard(makeSub())

    fireEvent.click(screen.getByText('Old Name'))
    fireEvent.blur(screen.getByDisplayValue('Old Name'))

    expect(onRename).not.toHaveBeenCalled()
  })

  it('cancels without committing on Escape', () => {
    const { onRename } = renderCard(makeSub())

    fireEvent.click(screen.getByText('Old Name'))
    const input = screen.getByDisplayValue('Old Name') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Discarded' } })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(onRename).not.toHaveBeenCalled()
    expect(screen.getByText('Old Name')).toBeInTheDocument()
  })

  it('starts editing from an empty field when the subscription has no name', () => {
    // Display falls back to the URL, but the editor edits the (empty) name.
    const { onRename } = renderCard(makeSub({ name: null }))

    fireEvent.click(screen.getByText('https://www.pixiv.net/users/12345'))
    const input = screen.getByPlaceholderText('Optional display name') as HTMLInputElement
    expect(input.value).toBe('')
    fireEvent.change(input, { target: { value: 'Named Now' } })
    fireEvent.blur(input)

    expect(onRename).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), 'Named Now')
  })
})
