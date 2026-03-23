/**
 * useDashboard — Vitest test suite
 *
 * Covers:
 *   useDashboard — passes 'download/dashboard' key to useSWR
 *   useDashboard — fetcher calls api.download.getDashboard
 *   useDashboard — sets refreshInterval: 5000 when not connected via WS
 *   useDashboard — sets refreshInterval: 0 when connected via WS
 *   useDashboard — returns the SWR result directly
 *
 * Note: The throttle/mutate useEffect is complex and fragile to test in
 * isolation — it is intentionally omitted. Focus is on SWR configuration.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const {
  mockGetDashboard,
  mockWsConnected,
  mockLastJobUpdate,
  mockLastEvent,
  mockUseSWR,
} = vi.hoisted(() => ({
  mockGetDashboard: vi.fn(),
  mockWsConnected: vi.fn(() => ({ connected: false })),
  mockLastJobUpdate: vi.fn(() => ({ lastJobUpdate: null, lastSubCheck: null })),
  mockLastEvent: vi.fn(() => ({ lastEvent: null })),
  mockUseSWR: vi.fn(),
}))

// ── Module mocks ──────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    download: {
      getDashboard: mockGetDashboard,
    },
  },
}))

vi.mock('@/lib/ws', () => ({
  useWsConnection: mockWsConnected,
  useWsJobs: mockLastJobUpdate,
  useWsEvents: mockLastEvent,
}))

// ── SWR mock — captures every call so we can inspect key/fetcher/options ──

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useDashboard } from '@/hooks/useDashboard'

// ── Helpers ───────────────────────────────────────────────────────────

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

function defaultSwrReturn() {
  return { data: undefined, isLoading: true, error: undefined, mutate: vi.fn() }
}

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockGetDashboard.mockResolvedValue({ queued: [], active: [], semaphores: {} })
  mockWsConnected.mockReturnValue({ connected: false })
  mockLastJobUpdate.mockReturnValue({ lastJobUpdate: null, lastSubCheck: null })
  mockLastEvent.mockReturnValue({ lastEvent: null })
  // Re-attach the capturing implementation after clearAllMocks
  mockUseSWR.mockImplementation(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return defaultSwrReturn()
    },
  )
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useDashboard — SWR key', () => {
  it('test_useDashboard_swrKey_isDownloadDashboard', () => {
    renderHook(() => useDashboard())

    expect(lastSwrCall().key).toBe('download/dashboard')
  })
})

describe('useDashboard — fetcher', () => {
  it('test_useDashboard_fetcher_callsApiDownloadGetDashboard', async () => {
    renderHook(() => useDashboard())

    await lastSwrCall().fetcher!()

    expect(mockGetDashboard).toHaveBeenCalledOnce()
  })
})

describe('useDashboard — refreshInterval', () => {
  it('test_useDashboard_notConnected_setsRefreshInterval5000', () => {
    mockWsConnected.mockReturnValue({ connected: false })

    renderHook(() => useDashboard())

    expect(lastSwrCall().options.refreshInterval).toBe(5000)
  })

  it('test_useDashboard_connected_setsRefreshInterval0', () => {
    mockWsConnected.mockReturnValue({ connected: true })

    renderHook(() => useDashboard())

    expect(lastSwrCall().options.refreshInterval).toBe(0)
  })
})

describe('useDashboard — return value', () => {
  it('test_useDashboard_returnValue_isSwrResult', () => {
    const fakeSwr = {
      data: { queued: [], active: [], semaphores: {} },
      isLoading: false,
      error: undefined,
      mutate: vi.fn(),
    }
    // mockImplementationOnce replaces the capturing impl for this one call
    mockUseSWR.mockImplementationOnce(
      (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
        swrCalls.push({ key, fetcher, options })
        return fakeSwr
      },
    )

    const { result } = renderHook(() => useDashboard())

    expect(result.current).toBe(fakeSwr)
  })

  it('test_useDashboard_returnValue_exposesDataField', () => {
    const payload = { queued: [{ id: '1' }], active: [], semaphores: {} }
    const swrWithData = {
      data: payload,
      isLoading: false,
      error: undefined,
      mutate: vi.fn(),
    }
    mockUseSWR.mockImplementationOnce(
      (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
        swrCalls.push({ key, fetcher, options })
        return swrWithData
      },
    )

    const { result } = renderHook(() => useDashboard())

    expect(result.current.data).toBe(payload)
  })
})
