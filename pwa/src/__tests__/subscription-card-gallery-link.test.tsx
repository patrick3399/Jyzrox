import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { DownloadJob, Subscription } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

const sub: Subscription = {
  id: 1,
  name: 'Artist subscription',
  url: 'https://example.com/users/1',
  source: 'x',
  source_id: '1',
  avatar_url: null,
  enabled: true,
  auto_download: true,
  cron_expr: null,
  last_checked_at: null,
  last_item_id: null,
  last_status: 'ok',
  last_error: null,
  next_check_at: null,
  created_at: null,
  last_job_id: 'job-1',
  group_id: null,
  paused_at: null,
  paused_reason: null,
  paused_until: null,
  checking: false,
  gallery_source: 'x',
  gallery_source_id: '1',
  gallery_title: 'Old A',
}

function makeJob(extra: Record<string, unknown>): DownloadJob {
  return {
    id: 'job-1',
    url: 'https://example.com/dl',
    source: 'x',
    status: 'done',
    progress: {},
    error: null,
    created_at: '2026-07-23T00:00:00Z',
    finished_at: '2026-07-23T00:01:00Z',
    retry_count: 0,
    max_retries: 3,
    next_retry_at: null,
    ...extra,
  } as DownloadJob
}

function renderCard(job: DownloadJob | null) {
  const noop = vi.fn()
  render(
    <SubscriptionCard
      sub={sub}
      latestJob={job}
      groups={[]}
      onToggle={noop}
      onCheck={noop}
      onBackfill={noop}
      onDelete={noop}
      onAutoDownloadToggle={noop}
      onMoveToGroup={noop}
      onRename={noop}
      checkingId={null}
    />,
  )
}

describe('SubscriptionCard gallery link and title come from the same gallery', () => {
  it('shows the job gallery title with the job gallery href when the latest job has its own gallery', () => {
    renderCard(makeJob({ gallery_source: 'x', gallery_source_id: '2', gallery_title: 'New B' }))

    const link = screen.getByRole('link', { name: 'New B' })
    expect(link).toHaveAttribute('href', '/library/x/2')
    expect(screen.queryByText('Old A')).not.toBeInTheDocument()
  })

  it('falls back to progress.title for the job gallery when the job has no gallery_title', () => {
    renderCard(
      makeJob({ gallery_source: 'x', gallery_source_id: '2', progress: { title: 'Progress B' } }),
    )

    const link = screen.getByRole('link', { name: 'Progress B' })
    expect(link).toHaveAttribute('href', '/library/x/2')
  })

  it('shows the subscription gallery title and href when the latest job has no gallery', () => {
    renderCard(makeJob({ progress: { title: 'Stale progress title' } }))

    const link = screen.getByRole('link', { name: 'Old A' })
    expect(link).toHaveAttribute('href', '/library/x/1')
  })
})
