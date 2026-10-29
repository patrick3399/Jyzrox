import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({
  jobs: vi.fn(),
  stop: vi.fn(),
  cancel: vi.fn(),
  enqueue: vi.fn(),
  check: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))
vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${Object.values(params).join(',')}` : key,
}))
vi.mock('@/lib/ws', () => ({ useWsConnection: () => ({ connected: true }) }))
vi.mock('@/lib/api', () => ({ api: { subscriptions: { check: h.check } } }))
vi.mock('@/hooks/useDownloadQueue', () => {
  const idle = { trigger: vi.fn(), isMutating: false }
  return {
    // The page lists manual and subscription jobs separately; serve jobs only to the manual list.
    useDownloadJobs: (params?: { subscription_only?: boolean }) => ({
      data: params?.subscription_only ? { total: 0, jobs: [] } : h.jobs(),
      isLoading: false,
      error: undefined,
      mutate: vi.fn(),
    }),
    useEnqueueDownload: () => ({ trigger: h.enqueue, isMutating: false }),
    useCancelJob: () => ({ trigger: h.cancel, isMutating: false }),
    useStopJob: () => ({ trigger: h.stop, isMutating: false }),
    useClearFinishedJobs: () => idle,
    usePauseJob: () => idle,
    useRetryJob: () => idle,
    useCheckUrl: () => ({ data: undefined }),
    useSupportedSites: () => ({ data: undefined }),
    useDownloadPreview: () => ({ data: undefined, isLoading: false }),
  }
})

type Mode = 'download' | 'subscription_initial' | 'subscription_incremental' | 'repair'

const job = (over: Record<string, unknown> = {}) => ({
  id: 'job-1',
  url: 'https://example.test/g/1',
  source: 'ehentai',
  status: 'running' as const,
  progress: {},
  error: null,
  created_at: '2026-10-30T10:00:00Z',
  finished_at: null,
  retry_count: 0,
  max_retries: 3,
  mode: 'download' as Mode,
  stop_requested_at: null as string | null,
  ...over,
})

const serve = (...jobs: ReturnType<typeof job>[]) =>
  h.jobs.mockReturnValue({ total: jobs.length, jobs })

async function renderQueue() {
  const { default: QueuePage } = await import('@/app/queue/page')
  render(<QueuePage />)
}

describe('queue stop / discard actions', () => {
  beforeEach(() => {
    h.jobs.mockReset()
    h.stop.mockReset().mockResolvedValue({ status: 'running', stopping: true })
    h.cancel.mockReset()
    h.enqueue.mockReset()
    h.check.mockReset().mockResolvedValue({ status: 'queued' })
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('stop button calls stopJob and shows stopping state', async () => {
    serve(job())
    await renderQueue()

    fireEvent.click(screen.getByTestId('job-stop'))

    await waitFor(() => expect(h.stop).toHaveBeenCalledWith('job-1'))
    // A manual download gives nothing up by stopping, so there is no confirm.
    expect(window.confirm).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByTestId('job-stop')).toBeDisabled())
    expect(screen.getByTestId('job-stop')).toHaveTextContent('queue.stopping')
    expect(screen.getByTestId('job-discard')).toBeDisabled()
    expect(h.cancel).not.toHaveBeenCalled()
  })

  it('shows the stopping state and disables both buttons while stop_requested_at is set', async () => {
    serve(job({ stop_requested_at: '2026-10-30T10:05:00Z' }))
    await renderQueue()

    expect(screen.getByTestId('job-stop')).toBeDisabled()
    expect(screen.getByTestId('job-stop')).toHaveTextContent('queue.stopping')
    expect(screen.getByTestId('job-discard')).toBeDisabled()
  })

  it('stopping a subscription job asks for confirmation and does not stop when declined', async () => {
    serve(job({ mode: 'subscription_incremental', subscription_id: 4 }))
    vi.stubGlobal('confirm', vi.fn(() => false))
    await renderQueue()

    fireEvent.click(screen.getByTestId('job-stop'))

    expect(window.confirm).toHaveBeenCalledWith('queue.stopConfirm')
    expect(h.stop).not.toHaveBeenCalled()
  })

  it('stopping a subscription job stops it once confirmed', async () => {
    serve(job({ mode: 'subscription_initial', subscription_id: 4 }))
    await renderQueue()

    fireEvent.click(screen.getByTestId('job-stop'))

    await waitFor(() => expect(h.stop).toHaveBeenCalledWith('job-1'))
  })

  it('discard hidden for repair jobs', async () => {
    serve(job({ mode: 'repair' }))
    await renderQueue()

    expect(screen.getByTestId('job-stop')).toBeInTheDocument()
    expect(screen.queryByTestId('job-discard')).not.toBeInTheDocument()
  })

  it('discard is offered for a manual download job and asks for confirmation first', async () => {
    serve(job())
    vi.stubGlobal('confirm', vi.fn(() => false))
    await renderQueue()

    fireEvent.click(screen.getByTestId('job-discard'))

    expect(window.confirm).toHaveBeenCalledWith('queue.discardConfirm')
    expect(h.cancel).not.toHaveBeenCalled()
  })

  it('shows a mode badge for repair and none for a manual download', async () => {
    serve(job({ id: 'job-r', mode: 'repair' }), job({ id: 'job-d', mode: 'download' }))
    await renderQueue()

    const badges = screen.getAllByTestId('job-mode-badge')
    expect(badges).toHaveLength(1)
    expect(badges[0]).toHaveTextContent('queue.modeRepair')
  })
})

describe('queue enqueue of a subscribed URL', () => {
  const subscribedError = () =>
    Object.assign(new Error('Conflict'), {
      status: 409,
      detail: { code: 'subscribed', subscription_id: 5, name: 'Some Artist' },
    })

  async function submitUrl() {
    serve()
    await renderQueue()
    fireEvent.change(screen.getByPlaceholderText('queue.urlPlaceholder'), {
      target: { value: 'https://example.test/artist/9' },
    })
    fireEvent.keyDown(screen.getByPlaceholderText('queue.urlPlaceholder'), { key: 'Enter' })
  }

  beforeEach(() => {
    h.jobs.mockReset()
    h.enqueue.mockReset()
    h.check.mockReset().mockResolvedValue({ status: 'queued' })
  })

  it('subscribed 409 opens dialog', async () => {
    h.enqueue.mockRejectedValueOnce(subscribedError())
    await submitUrl()

    expect(await screen.findByTestId('subscribed-dialog')).toBeInTheDocument()
    expect(h.enqueue).toHaveBeenCalledTimes(1)
    expect(h.enqueue.mock.calls[0][0]).not.toHaveProperty('confirmSubscribed')
  })

  it('download anyway re-submits with confirmSubscribed', async () => {
    h.enqueue.mockRejectedValueOnce(subscribedError()).mockResolvedValueOnce({ job_id: 'j2' })
    await submitUrl()

    fireEvent.click(await screen.findByTestId('subscribed-download-anyway'))

    await waitFor(() => expect(h.enqueue).toHaveBeenCalledTimes(2))
    expect(h.enqueue.mock.calls[1][0]).toMatchObject({
      url: 'https://example.test/artist/9',
      confirmSubscribed: true,
    })
    await waitFor(() => expect(screen.queryByTestId('subscribed-dialog')).not.toBeInTheDocument())
  })

  it('check now triggers a subscription check instead of a download', async () => {
    h.enqueue.mockRejectedValueOnce(subscribedError())
    await submitUrl()

    fireEvent.click(await screen.findByTestId('subscribed-check-now'))

    await waitFor(() => expect(h.check).toHaveBeenCalledWith(5))
    expect(h.enqueue).toHaveBeenCalledTimes(1)
  })

  it('an unrelated enqueue error does not open the subscribed dialog', async () => {
    h.enqueue.mockRejectedValueOnce(new Error('boom'))
    await submitUrl()

    await waitFor(() => expect(h.enqueue).toHaveBeenCalledTimes(1))
    expect(screen.queryByTestId('subscribed-dialog')).not.toBeInTheDocument()
  })
})
