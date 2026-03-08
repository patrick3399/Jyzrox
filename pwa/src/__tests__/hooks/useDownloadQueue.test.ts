/**
 * useDownloadQueue — Vitest test suite
 *
 * Covers:
 *   useDownloadJobs      — passes key ['download/jobs', params] to useSWR
 *   useDownloadJobs      — configured with refreshInterval: 3000
 *   useDownloadJobs      — fetcher calls api.download.getJobs with the params
 *   useEnqueueDownload   — trigger() calls api.download.enqueue with the given URL
 *   useCancelJob         — trigger() calls api.download.cancelJob with the job ID
 *   useClearFinishedJobs — trigger() calls api.download.clearFinishedJobs
 *   useDownloadStats     — passes key "download/stats" and refreshInterval: 5000
 *   usePauseJob          — trigger() with action:"pause" calls api.download.pauseJob
 *   usePauseJob          — trigger() with action:"resume" calls api.download.resumeJob
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations. Variables used
 *   inside a factory must be created with vi.hoisted() to be available at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const {
  mockEnqueue,
  mockGetJobs,
  mockCancelJob,
  mockClearFinishedJobs,
  mockGetStats,
  mockPauseJob,
  mockResumeJob,
} = vi.hoisted(() => ({
  mockEnqueue: vi.fn(),
  mockGetJobs: vi.fn(),
  mockCancelJob: vi.fn(),
  mockClearFinishedJobs: vi.fn(),
  mockGetStats: vi.fn(),
  mockPauseJob: vi.fn(),
  mockResumeJob: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    download: {
      enqueue: mockEnqueue,
      getJobs: mockGetJobs,
      cancelJob: mockCancelJob,
      clearFinishedJobs: mockClearFinishedJobs,
      getStats: mockGetStats,
      pauseJob: mockPauseJob,
      resumeJob: mockResumeJob,
    },
  },
}))

// ── swr / swr/mutation mocks ──────────────────────────────────────────

// We capture key, fetcher, and options from every useSWR call.
interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

const { mockUseSWR, mockUseSWRMutation } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: true, error: undefined }
    },
  ),
  // useSWRMutation: expose a trigger that calls the fetcher with the arg.
  mockUseSWRMutation: vi.fn(
    (_key: unknown, fetcher: (_k: unknown, extra: { arg: unknown }) => unknown) => ({
      trigger: (arg: unknown) => fetcher(_key, { arg }),
      isMutating: false,
    }),
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

vi.mock('swr/mutation', () => ({
  default: mockUseSWRMutation,
}))

// ── Import hooks after mocks ──────────────────────────────────────────

import {
  useDownloadJobs,
  useEnqueueDownload,
  useCancelJob,
  useClearFinishedJobs,
  useDownloadStats,
  usePauseJob,
} from '@/hooks/useDownloadQueue'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0

  mockGetJobs.mockResolvedValue({ total: 0, jobs: [] })
  mockEnqueue.mockResolvedValue({ job_id: 'abc', status: 'queued' })
  mockCancelJob.mockResolvedValue({ status: 'cancelled' })
  mockClearFinishedJobs.mockResolvedValue({ deleted: 3 })
  mockGetStats.mockResolvedValue({ running: 0, finished: 5 })
  mockPauseJob.mockResolvedValue({ status: 'paused' })
  mockResumeJob.mockResolvedValue({ status: 'running' })
})

afterEach(() => {
  vi.clearAllMocks()
})

// Helper: run a hook and return the captured SWR call (first call in the batch).
function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useDownloadJobs', () => {
  it('should call useSWR once and return its result', () => {
    const result = useDownloadJobs()
    expect(mockUseSWR).toHaveBeenCalledOnce()
    expect(result).toMatchObject({ data: undefined, isLoading: true })
  })

  it('should pass a key with "download/jobs" as the first element', () => {
    useDownloadJobs()
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('download/jobs')
  })

  it('should include the params object as the second element of the key', () => {
    const params = { status: 'running' } as never
    useDownloadJobs(params)
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toEqual(params)
  })

  it('should configure SWR with refreshInterval: 3000', () => {
    useDownloadJobs()
    expect(lastSwrCall().options.refreshInterval).toBe(3000)
  })

  it('should call api.download.getJobs with the params when the fetcher runs', async () => {
    useDownloadJobs({ status: 'running' } as never)
    await lastSwrCall().fetcher!()
    expect(mockGetJobs).toHaveBeenCalledWith({ status: 'running' })
  })
})

describe('useEnqueueDownload', () => {
  it('should call useSWRMutation with key "download/enqueue"', () => {
    useEnqueueDownload()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('download/enqueue')
  })

  it('should call api.download.enqueue with the URL when trigger is invoked', async () => {
    const { trigger } = useEnqueueDownload()
    await trigger({ url: 'https://example.com/gallery/1' })
    expect(mockEnqueue).toHaveBeenCalledOnce()
    expect(mockEnqueue).toHaveBeenCalledWith('https://example.com/gallery/1')
  })
})

describe('useCancelJob', () => {
  it('should call useSWRMutation with key "download/cancel"', () => {
    useCancelJob()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('download/cancel')
  })

  it('should call api.download.cancelJob with the job ID when trigger is invoked', async () => {
    const { trigger } = useCancelJob()
    await trigger('job-42')
    expect(mockCancelJob).toHaveBeenCalledOnce()
    expect(mockCancelJob).toHaveBeenCalledWith('job-42')
  })
})

describe('useClearFinishedJobs', () => {
  it('should call useSWRMutation with key "download/clear"', () => {
    useClearFinishedJobs()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('download/clear')
  })

  it('should call api.download.clearFinishedJobs when trigger is invoked', async () => {
    const { trigger } = useClearFinishedJobs()
    await trigger(undefined)
    expect(mockClearFinishedJobs).toHaveBeenCalledOnce()
  })
})

describe('useDownloadStats', () => {
  it('should call useSWR with key "download/stats"', () => {
    useDownloadStats()
    expect(lastSwrCall().key).toBe('download/stats')
  })

  it('should configure SWR with refreshInterval: 5000', () => {
    useDownloadStats()
    expect(lastSwrCall().options.refreshInterval).toBe(5000)
  })

  it('should call api.download.getStats when the SWR fetcher runs', async () => {
    useDownloadStats()
    await lastSwrCall().fetcher!()
    expect(mockGetStats).toHaveBeenCalledOnce()
  })
})

describe('usePauseJob', () => {
  it('should call useSWRMutation with key "download/pause"', () => {
    usePauseJob()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('download/pause')
  })

  it('should call api.download.pauseJob when trigger is invoked with action "pause"', async () => {
    const { trigger } = usePauseJob()
    await trigger({ id: 'job-7', action: 'pause' })
    expect(mockPauseJob).toHaveBeenCalledOnce()
    expect(mockPauseJob).toHaveBeenCalledWith('job-7')
    expect(mockResumeJob).not.toHaveBeenCalled()
  })

  it('should call api.download.resumeJob when trigger is invoked with action "resume"', async () => {
    const { trigger } = usePauseJob()
    await trigger({ id: 'job-7', action: 'resume' })
    expect(mockResumeJob).toHaveBeenCalledOnce()
    expect(mockResumeJob).toHaveBeenCalledWith('job-7')
    expect(mockPauseJob).not.toHaveBeenCalled()
  })
})
