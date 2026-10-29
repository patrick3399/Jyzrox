import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

interface TestJob {
  id: string
  url: string
  source: string
  status: 'queued' | 'running' | 'paused' | 'done'
  progress: Record<string, unknown>
  error: null
  created_at: string
  finished_at: string | null
  retry_count: number
  max_retries: number
  subscription_id?: number | null
}

const mockUseDownloadJobs = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${Object.values(params).join(',')}` : key,
}))

vi.mock('@/lib/ws', () => ({
  useWsConnection: () => ({ connected: true }),
}))

vi.mock('@/lib/api', () => ({ api: {} }))

vi.mock('@/hooks/useDownloadQueue', () => {
  const trigger = { trigger: vi.fn(), isMutating: false }
  return {
    useDownloadJobs: (params: Record<string, unknown>) => mockUseDownloadJobs(params),
    useEnqueueDownload: () => trigger,
    useCancelJob: () => trigger,
    useStopJob: () => trigger,
    useClearFinishedJobs: () => trigger,
    usePauseJob: () => trigger,
    useRetryJob: () => trigger,
    useCheckUrl: () => ({ data: undefined }),
    useSupportedSites: () => ({ data: undefined }),
    useDownloadPreview: () => ({ data: undefined, isLoading: false }),
  }
})

const makeJob = (
  id: string,
  status: TestJob['status'],
  subscription_id: number | null,
  created_at = '2026-10-15T14:00:00Z',
): TestJob => ({
  id,
  url: `https://example.test/${id}`,
  source: 'ehentai',
  status,
  progress: {},
  error: null,
  created_at,
  finished_at: status === 'done' ? '2026-10-15T15:00:00Z' : null,
  retry_count: 0,
  max_retries: 3,
  subscription_id,
})

/** Route the two useDownloadJobs calls by their params, like the real SWR key does. */
function serveJobs(
  manual: { total: number; jobs: TestJob[] },
  sub: { total: number; jobs: TestJob[] },
) {
  mockUseDownloadJobs.mockImplementation((params: Record<string, unknown>) => ({
    data: params?.subscription_only ? sub : manual,
    isLoading: false,
    error: undefined,
    mutate: vi.fn(),
  }))
}

async function renderQueue() {
  const { default: QueuePage } = await import('@/app/queue/page')
  render(<QueuePage />)
}

describe('queue subscription-active section', () => {
  beforeEach(() => {
    mockUseDownloadJobs.mockReset()
  })

  it('lists the active subscription jobs with the header count', async () => {
    serveJobs(
      { total: 0, jobs: [] },
      {
        total: 3,
        jobs: [
          makeJob('sub-queued', 'queued', 1),
          makeJob('sub-running', 'running', 2),
          makeJob('sub-paused', 'paused', 3),
        ],
      },
    )
    await renderQueue()

    const section = document.getElementById('subscription-active')
    expect(section).not.toBeNull()
    const scope = within(section as HTMLElement)
    expect(scope.getByText('queue.subscriptionActive (3)')).toBeInTheDocument()
    expect(scope.getByText('https://example.test/sub-queued')).toBeInTheDocument()
    expect(scope.getByText('https://example.test/sub-running')).toBeInTheDocument()
    expect(scope.getByText('https://example.test/sub-paused')).toBeInTheDocument()
  })

  it('orders running before paused before queued', async () => {
    serveJobs(
      { total: 0, jobs: [] },
      {
        total: 3,
        jobs: [
          makeJob('sub-queued', 'queued', 1),
          makeJob('sub-paused', 'paused', 2),
          makeJob('sub-running', 'running', 3),
        ],
      },
    )
    await renderQueue()

    const section = document.getElementById('subscription-active') as HTMLElement
    const text = section.textContent ?? ''
    expect(text.indexOf('sub-running')).toBeGreaterThan(-1)
    expect(text.indexOf('sub-running')).toBeLessThan(text.indexOf('sub-paused'))
    expect(text.indexOf('sub-paused')).toBeLessThan(text.indexOf('sub-queued'))
  })

  it('does not render the section when there are no active subscription jobs', async () => {
    serveJobs({ total: 1, jobs: [makeJob('manual-1', 'running', null)] }, { total: 0, jobs: [] })
    await renderQueue()

    expect(document.getElementById('subscription-active')).toBeNull()
    expect(screen.queryByText(/queue\.subscriptionActive/)).not.toBeInTheDocument()
  })

  it('does not show a done job returned in the subscription list', async () => {
    serveJobs(
      { total: 0, jobs: [] },
      {
        total: 2,
        jobs: [makeJob('sub-running', 'running', 1), makeJob('sub-finished', 'done', 1)],
      },
    )
    await renderQueue()

    const section = document.getElementById('subscription-active') as HTMLElement
    const scope = within(section)
    expect(scope.getByText('https://example.test/sub-running')).toBeInTheDocument()
    expect(scope.queryByText('https://example.test/sub-finished')).not.toBeInTheDocument()
    // The count reflects only what is rendered, not the stale done row.
    expect(scope.getByText('queue.subscriptionActive (1)')).toBeInTheDocument()
  })

  it('does not render the section when the subscription list only holds finished jobs', async () => {
    serveJobs({ total: 0, jobs: [] }, { total: 1, jobs: [makeJob('sub-finished', 'done', 1)] })
    await renderQueue()

    expect(document.getElementById('subscription-active')).toBeNull()
  })

  it('keeps manual jobs out of the subscription section', async () => {
    serveJobs(
      { total: 1, jobs: [makeJob('manual-1', 'running', null)] },
      { total: 1, jobs: [makeJob('sub-running', 'running', 4)] },
    )
    await renderQueue()

    const section = document.getElementById('subscription-active') as HTMLElement
    expect(within(section).queryByText('https://example.test/manual-1')).not.toBeInTheDocument()
    expect(screen.getByText('https://example.test/manual-1')).toBeInTheDocument()
  })

  it('shows the truncation note when total exceeds the rendered jobs', async () => {
    serveJobs({ total: 0, jobs: [] }, { total: 150, jobs: [makeJob('sub-running', 'running', 1)] })
    await renderQueue()

    expect(screen.getByText('queue.subscriptionActive (150)')).toBeInTheDocument()
    expect(screen.getByText('queue.subscriptionActiveTruncated:1,150')).toBeInTheDocument()
  })

  it('queries the manual list with exclude_subscription and the subscription list with active-only params', async () => {
    serveJobs({ total: 0, jobs: [] }, { total: 0, jobs: [] })
    await renderQueue()

    const calls = mockUseDownloadJobs.mock.calls.map(([params]) => params)
    expect(calls).toContainEqual({ exclude_subscription: true })
    expect(calls).toContainEqual({ subscription_only: true, active_only: true, limit: 100 })
  })
})
