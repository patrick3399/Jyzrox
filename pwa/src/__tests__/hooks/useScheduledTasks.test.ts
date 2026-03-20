/**
 * useScheduledTasks — Vitest test suite
 *
 * Covers:
 *   useScheduledTasks — passes key 'scheduled-tasks' to useSWR
 *   useScheduledTasks — fetcher calls api.scheduledTasks.list
 *   useScheduledTasks — passes refreshInterval option through to SWR
 *   useUpdateTask     — trigger calls api.scheduledTasks.update with taskId and data
 *   useRunTask        — trigger calls api.scheduledTasks.run with taskId
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockList, mockUpdate, mockRun } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockUpdate: vi.fn(),
  mockRun: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    scheduledTasks: {
      list: mockList,
      update: mockUpdate,
      run: mockRun,
    },
  },
}))

// ── swr / swr/mutation mocks ──────────────────────────────────────────

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

import { useScheduledTasks, useUpdateTask, useRunTask } from '@/hooks/useScheduledTasks'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockList.mockResolvedValue([])
  mockUpdate.mockResolvedValue({ taskId: 'test', enabled: true })
  mockRun.mockResolvedValue({ status: 'started' })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useScheduledTasks', () => {
  it('test_useScheduledTasks_key_isScheduledTasksString', () => {
    useScheduledTasks()
    expect(lastSwrCall().key).toBe('scheduled-tasks')
  })

  it('test_useScheduledTasks_fetcher_callsApiScheduledTasksList', async () => {
    useScheduledTasks()
    await lastSwrCall().fetcher!()
    expect(mockList).toHaveBeenCalledOnce()
  })

  it('test_useScheduledTasks_withRefreshInterval_passesOptionToSwr', () => {
    useScheduledTasks(10000)
    expect(lastSwrCall().options.refreshInterval).toBe(10000)
  })

  it('test_useScheduledTasks_withoutRefreshInterval_passesUndefined', () => {
    useScheduledTasks()
    expect(lastSwrCall().options.refreshInterval).toBeUndefined()
  })
})

describe('useUpdateTask', () => {
  it('test_useUpdateTask_key_isScheduledTasks', () => {
    useUpdateTask()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('scheduled-tasks')
  })

  it('test_useUpdateTask_trigger_callsApiScheduledTasksUpdateWithTaskIdAndData', async () => {
    const { trigger } = useUpdateTask()
    await trigger({ taskId: 'weekly-scan', data: { enabled: true, cron_expr: '0 3 * * 0' } })
    expect(mockUpdate).toHaveBeenCalledWith('weekly-scan', {
      enabled: true,
      cron_expr: '0 3 * * 0',
    })
  })
})

describe('useRunTask', () => {
  it('test_useRunTask_key_isScheduledTasks', () => {
    useRunTask()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('scheduled-tasks')
  })

  it('test_useRunTask_trigger_callsApiScheduledTasksRunWithTaskId', async () => {
    const { trigger } = useRunTask()
    await trigger('dedup-scan')
    expect(mockRun).toHaveBeenCalledWith('dedup-scan')
  })
})
