import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { DownloadJob, Subscription, SubscriptionRun } from '@/lib/types'
import { SubscriptionCard } from '@/components/subscriptions/SubscriptionCard'

const h = vi.hoisted(() => ({
  pauseJob: vi.fn(async () => ({ status: 'paused' })),
  resumeJob: vi.fn(async () => ({ status: 'running' })),
  pause: vi.fn(async () => ({ status: 'ok', paused_jobs: 3 })),
  resume: vi.fn(async () => ({ status: 'ok', resumed_jobs: 3 })),
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      download: { ...actual.api.download, pauseJob: h.pauseJob, resumeJob: h.resumeJob },
      subscriptions: { ...actual.api.subscriptions, pause: h.pause, resume: h.resume },
    },
  }
})

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

const sub: Subscription = {
  id: 283,
  name: 'Fanbox creator',
  url: 'https://www.fanbox.cc/@creator',
  source: 'fanbox',
  source_id: 'creator',
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
}

const zeroRun: SubscriptionRun = {
  total: 0,
  queued: 0,
  running: 0,
  paused: 0,
  done: 0,
  stopped: 0,
  failed: 0,
  partial: 0,
  cancelled: 0,
}

const activeRun: SubscriptionRun = { ...zeroRun, total: 754, done: 60, running: 1, queued: 693 }

function makeJob(status: DownloadJob['status'], title = 'Post X'): DownloadJob {
  return {
    id: 'job-1',
    url: 'https://www.fanbox.cc/@creator/posts/1',
    source: 'fanbox',
    status,
    progress: { title, downloaded: 2, total: 5 },
    error: null,
    created_at: '2026-11-07T00:00:00Z',
    finished_at: null,
    retry_count: 0,
    max_retries: 3,
    next_retry_at: null,
  }
}

function renderCard(
  overrides: Partial<Subscription> = {},
  run: SubscriptionRun | null = activeRun,
  job: DownloadJob | null = makeJob('running'),
) {
  const noop = vi.fn()
  render(
    <SubscriptionCard
      sub={{ ...sub, ...overrides }}
      latestJob={job}
      run={run}
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

beforeEach(() => vi.clearAllMocks())

describe('SubscriptionCard run control', () => {
  it('multi-job run shows done/total posts and the running post title', () => {
    renderCard({}, activeRun, makeJob('running', 'Post X'))

    expect(screen.getByText(/60 \/ 754/)).toBeInTheDocument()
    expect(screen.getByText(/Post X/)).toBeInTheDocument()
  })

  it('pause button pauses the subscription, not the single job', async () => {
    renderCard()

    fireEvent.click(screen.getByTestId('subscription-pause'))
    await waitFor(() => expect(h.pause).toHaveBeenCalledWith(283))
    expect(h.pauseJob).not.toHaveBeenCalled()
  })

  it('run with only queued jobs still offers pause', async () => {
    renderCard({}, { ...zeroRun, total: 10, queued: 10 }, makeJob('queued'))

    fireEvent.click(screen.getByTestId('subscription-pause'))
    await waitFor(() => expect(h.pause).toHaveBeenCalledWith(283))
  })

  it('resume button on a paused subscription resumes the subscription, not the single job', async () => {
    renderCard(
      { paused_at: '2026-11-07T01:00:00+00:00', paused_reason: 'manual' },
      { ...zeroRun, total: 754, done: 60, paused: 694 },
      makeJob('paused'),
    )

    fireEvent.click(screen.getByTestId('subscription-resume'))
    await waitFor(() => expect(h.resume).toHaveBeenCalledWith(283))
    expect(h.resumeJob).not.toHaveBeenCalled()
  })

  it('paused subscription shows resume and disables check and backfill', () => {
    renderCard(
      { paused_at: '2026-11-07T01:00:00+00:00', paused_reason: 'manual' },
      { ...zeroRun, total: 754, done: 60, paused: 694 },
      makeJob('paused'),
    )

    expect(screen.getByTestId('subscription-resume')).toBeInTheDocument()
    expect(screen.queryByTestId('subscription-pause')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download Now' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    expect(screen.getByRole('button', { name: 'Force re-scan' })).toBeDisabled()
  })

  it('rate-limited pause shows the auto-resume text', () => {
    renderCard(
      {
        paused_at: '2026-11-07T01:00:00+00:00',
        paused_reason: 'rate_limited',
        paused_until: '2026-11-07T01:30:00+00:00',
      },
      { ...zeroRun, total: 10, paused: 10 },
      makeJob('paused'),
    )

    expect(screen.getByText(/Rate limited/)).toBeInTheDocument()
  })

  it('auth pause asks to update the credential', () => {
    renderCard(
      { paused_at: '2026-11-07T01:00:00+00:00', paused_reason: 'auth' },
      { ...zeroRun, total: 10, paused: 10 },
      makeJob('paused'),
    )

    expect(screen.getByText(/Login expired/)).toBeInTheDocument()
  })

  it('checking subscription shows a checking badge and disables check', () => {
    renderCard({ checking: true }, null, null)

    expect(screen.getByText(/Checking/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download Now' })).toBeDisabled()
  })

  it('idle subscription with a finished run shows no pause control', () => {
    renderCard({}, { ...zeroRun, total: 5, done: 5 }, { ...makeJob('done') })

    expect(screen.queryByTestId('subscription-pause')).not.toBeInTheDocument()
  })
})
