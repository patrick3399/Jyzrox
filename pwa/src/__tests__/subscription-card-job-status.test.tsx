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
  url: 'https://www.pixiv.net/users/12345',
  source: 'pixiv',
  source_id: '12345',
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
}

function makeJob(status: DownloadJob['status']): DownloadJob {
  return {
    id: 'job-1',
    url: 'https://www.pixiv.net/artworks/67890',
    source: 'pixiv',
    status,
    gallery_source: 'pixiv',
    gallery_source_id: '67890',
    progress: { title: 'Always visible gallery', downloaded: 10, total: 10 },
    error: null,
    created_at: '2026-07-23T00:00:00Z',
    finished_at: status === 'done' ? '2026-07-23T00:01:00Z' : null,
    retry_count: 0,
    max_retries: 3,
    next_retry_at: null,
  }
}

function renderCard(job: DownloadJob | null, overrides: Partial<Subscription> = {}) {
  const noop = vi.fn()
  render(
    <SubscriptionCard
      sub={{ ...sub, ...overrides }}
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

describe('SubscriptionCard job gallery title', () => {
  it.each(['running', 'done'] as const)(
    'keeps the gallery title visible when the job is %s',
    (status) => {
      renderCard(makeJob(status))

      const title = screen.getByRole('link', { name: 'Always visible gallery' })
      expect(title).toHaveAttribute('href', '/library/pixiv/67890')
    },
  )

  it('renders the completed status separately from the gallery title', () => {
    renderCard(makeJob('done'))

    expect(screen.getByText('Download complete')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View Gallery' })).not.toBeInTheDocument()
  })

  it('uses the current gallery title when an old subscription has no latest job', () => {
    renderCard(null, {
      last_job_id: null,
      gallery_source: 'pixiv',
      gallery_source_id: '67890',
      gallery_title: 'Current renamed gallery',
    })

    expect(screen.getByRole('link', { name: 'Current renamed gallery' })).toHaveAttribute(
      'href',
      '/library/pixiv/67890',
    )
    expect(screen.queryByRole('link', { name: 'View Gallery' })).not.toBeInTheDocument()
  })

  it('prefers the current gallery title over a stale job title', () => {
    renderCard(makeJob('done'), { gallery_title: 'Renamed gallery' })

    expect(screen.getByRole('link', { name: 'Renamed gallery' })).toBeInTheDocument()
    expect(screen.queryByText('Always visible gallery')).not.toBeInTheDocument()
  })
})
