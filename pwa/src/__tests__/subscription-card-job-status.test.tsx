import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { DownloadJob, Subscription } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'

const h = vi.hoisted(() => ({
  pauseJob: vi.fn(async () => ({ status: 'paused' })),
  resumeJob: vi.fn(async () => ({ status: 'running' })),
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      download: { ...actual.api.download, pauseJob: h.pauseJob, resumeJob: h.resumeJob },
    },
  }
})

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

  it('keeps low-frequency actions collapsed behind the compact more control', () => {
    renderCard(makeJob('done'))

    expect(screen.getByRole('button', { name: 'Download Now' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'URL' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Force re-scan' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'More' }))

    expect(screen.getByRole('link', { name: 'URL' })).toHaveAttribute('href', sub.url)
    expect(screen.getByRole('button', { name: 'Force re-scan' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Subscription Feed' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })
})

describe('SubscriptionCard active job controls', () => {
  it('offers pause and stop while the subscription job is running', () => {
    renderCard(makeJob('running'))

    expect(screen.getByTestId('subscription-pause')).toBeInTheDocument()
    expect(screen.getByTestId('subscription-stop')).toBeInTheDocument()
    expect(screen.queryByTestId('subscription-resume')).not.toBeInTheDocument()
  })

  it('offers resume instead of pause while the subscription job is paused', async () => {
    renderCard(makeJob('paused'))

    expect(screen.queryByTestId('subscription-pause')).not.toBeInTheDocument()
    expect(screen.getByTestId('subscription-stop')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('subscription-resume'))
    await waitFor(() => expect(h.resumeJob).toHaveBeenCalledWith('job-1'))
  })

  it('pauses the latest job by id', async () => {
    renderCard(makeJob('running'))

    fireEvent.click(screen.getByTestId('subscription-pause'))
    await waitFor(() => expect(h.pauseJob).toHaveBeenCalledWith('job-1'))
  })

  it('hides pause once a stop was requested so the stop is not undone', () => {
    renderCard({ ...makeJob('running'), stop_requested_at: '2026-07-23T00:00:30Z' })

    expect(screen.queryByTestId('subscription-pause')).not.toBeInTheDocument()
    expect(screen.getByTestId('subscription-stop')).toBeDisabled()
  })

  it.each(['done', 'failed', 'cancelled'] as const)(
    'shows no job controls when the latest job is %s',
    (status) => {
      renderCard(makeJob(status))

      expect(screen.queryByTestId('subscription-pause')).not.toBeInTheDocument()
      expect(screen.queryByTestId('subscription-resume')).not.toBeInTheDocument()
      expect(screen.queryByTestId('subscription-stop')).not.toBeInTheDocument()
    },
  )
})
