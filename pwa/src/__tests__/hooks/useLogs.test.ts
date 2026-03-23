/**
 * useLogs / useLogStream hooks — Vitest test suite
 *
 * Covers:
 *   useLogs passes JSON.stringify(['logs', params]) as key to useSWR
 *   useLogs fetcher calls api.logs.list with params
 *   useLogs returns logs: [], total: 0, hasMore: false when data is undefined
 *   useLogStream starts with empty streamedLogs
 *   useLogStream clearStream resets to empty array
 *   useLogStream togglePause toggles isPaused
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockLogsList, mockLastLogEntry } = vi.hoisted(() => ({
  mockLogsList: vi.fn(),
  mockLastLogEntry: { current: null as unknown },
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    logs: {
      list: mockLogsList,
    },
  },
}))

// ── ws mock ───────────────────────────────────────────────────────────

vi.mock('@/lib/ws', () => ({
  useWsLogs: () => ({ lastLogEntry: mockLastLogEntry.current }),
}))

// ── swr mock ──────────────────────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

const { mockUseSWR } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: true, error: undefined, mutate: vi.fn() }
    },
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

// ── Import hooks after mocks ──────────────────────────────────────────

import { useLogs, useLogStream } from '@/hooks/useLogs'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockLastLogEntry.current = null
  mockLogsList.mockResolvedValue({ logs: [], total: 0, has_more: false })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useLogs', () => {
  it('test_useLogs_key_isJsonStringifiedLogsWithParams', () => {
    const params = { level: ['info'], source: 'worker', limit: 50, offset: 0 }
    useLogs(params)
    const { key } = lastSwrCall()
    expect(key).toBe(JSON.stringify(['logs', params]))
  })

  it('test_useLogs_fetcher_callsApiLogsListWithParams', async () => {
    const params = { search: 'error', limit: 100 }
    useLogs(params)
    await lastSwrCall().fetcher!()
    expect(mockLogsList).toHaveBeenCalledWith(params)
  })

  it('test_useLogs_undefinedData_returnsEmptyLogsZeroTotalFalseHasMore', () => {
    // mockUseSWR returns { data: undefined } by default
    const result = useLogs({})
    expect(result.logs).toEqual([])
    expect(result.total).toBe(0)
    expect(result.hasMore).toBe(false)
  })

  it('test_useLogs_emptyParams_usesJsonStringifiedKey', () => {
    const params = {}
    useLogs(params)
    const { key } = lastSwrCall()
    expect(key).toBe(JSON.stringify(['logs', params]))
  })
})

describe('useLogStream', () => {
  it('test_useLogStream_initialState_streamedLogsIsEmpty', () => {
    const { result } = renderHook(() => useLogStream())
    expect(result.current.streamedLogs).toEqual([])
  })

  it('test_useLogStream_initialState_isPausedIsFalse', () => {
    const { result } = renderHook(() => useLogStream())
    expect(result.current.isPaused).toBe(false)
  })

  it('test_useLogStream_clearStream_resetsStreamedLogsToEmpty', () => {
    const { result } = renderHook(() => useLogStream())
    act(() => {
      result.current.clearStream()
    })
    expect(result.current.streamedLogs).toEqual([])
  })

  it('test_useLogStream_togglePause_togglesIsPausedToTrue', () => {
    const { result } = renderHook(() => useLogStream())
    act(() => {
      result.current.togglePause()
    })
    expect(result.current.isPaused).toBe(true)
  })

  it('test_useLogStream_togglePause_togglesIsPausedBackToFalse', () => {
    const { result } = renderHook(() => useLogStream())
    act(() => {
      result.current.togglePause()
    })
    act(() => {
      result.current.togglePause()
    })
    expect(result.current.isPaused).toBe(false)
  })
})
