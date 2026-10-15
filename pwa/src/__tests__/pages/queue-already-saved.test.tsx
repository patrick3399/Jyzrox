import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockJobs = vi.fn()

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
    useDownloadJobs: () => ({
      data: mockJobs(),
      isLoading: false,
      error: undefined,
      mutate: vi.fn(),
    }),
    useEnqueueDownload: () => trigger,
    useCancelJob: () => trigger,
    useClearFinishedJobs: () => trigger,
    usePauseJob: () => trigger,
    useRetryJob: () => trigger,
    useCheckUrl: () => ({ data: undefined }),
    useSupportedSites: () => ({ data: undefined }),
    useDownloadPreview: () => ({ data: undefined, isLoading: false }),
  }
})

const doneJob = (progress: Record<string, unknown>) => ({
  id: 'job-1',
  url: 'http://www.xiuren7.com/430738.html',
  source: 'unknown',
  status: 'done' as const,
  progress,
  error: null,
  created_at: '2026-10-15T14:08:13Z',
  finished_at: '2026-10-15T14:09:30Z',
  retry_count: 0,
  max_retries: 3,
  gallery_id: 7,
  gallery_source: 'xiuren7',
  gallery_source_id: 'gallery=430738',
})

async function renderQueue() {
  const { default: QueuePage } = await import('@/app/queue/page')
  render(<QueuePage />)
}

describe('queue job that only confirmed already-saved content', () => {
  beforeEach(() => {
    mockJobs.mockReset()
  })

  it('shows an already-saved badge and note instead of a bare done and a skipped count', async () => {
    mockJobs.mockReturnValue({
      total: 1,
      jobs: [
        doneJob({
          downloaded: 0,
          skipped: 10,
          outcome: 'already_saved',
          existing_pages: 85,
          title: 'No.8984',
        }),
      ],
    })
    await renderQueue()
    expect(screen.getByText('queue.statusAlreadySaved')).toBeInTheDocument()
    expect(screen.queryByText('done')).not.toBeInTheDocument()
    // The title links to the existing gallery.
    expect(screen.getByRole('link', { name: 'No.8984' })).toBeInTheDocument()

    fireEvent.click(screen.getByText('http://www.xiuren7.com/430738.html'))
    expect(screen.getByText('queue.alreadySavedNote:85')).toBeInTheDocument()
    // The abort:10 counter is not a page total and must not be presented as one.
    expect(screen.queryByText('queue.jobSkipped:')).not.toBeInTheDocument()
  })

  it('keeps the plain done badge and skipped count for a run that downloaded files', async () => {
    mockJobs.mockReturnValue({
      total: 1,
      jobs: [doneJob({ downloaded: 12, skipped: 3, title: 'No.1' })],
    })
    await renderQueue()
    expect(screen.getByText('done')).toBeInTheDocument()
    expect(screen.queryByText('queue.statusAlreadySaved')).not.toBeInTheDocument()
  })
})
