/**
 * useTimeRange — Vitest test suite
 *
 * Covers:
 *   useTimeRange — SWR key is ['library/images/time_range', params]
 *   useTimeRange — fetcher calls api.library.imageTimeRange with params
 *   useTimeRange — dedupingInterval is 300_000 (regression: missing dedup caused unnecessary refetches)
 *   useTimeRange — revalidateOnFocus is false
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations. Variables used inside
 *   a factory must be created with vi.hoisted() to be available at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const { mockImageTimeRange } = vi.hoisted(() => ({
  mockImageTimeRange: vi.fn(),
}))

// ── api mock ──────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      imageTimeRange: mockImageTimeRange,
    },
  },
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
      return { data: undefined, error: undefined }
    },
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useTimeRange } from '@/hooks/useTimeRange'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockImageTimeRange.mockResolvedValue({ min_at: null, max_at: null })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useTimeRange', () => {
  it('test_useTimeRange_key_firstElementIsLibraryImagesTimeRange', () => {
    useTimeRange()
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('library/images/time_range')
  })

  it('test_useTimeRange_key_secondElementIsTheParamsObject', () => {
    const params = { tags: ['tag1'], source: 'ehentai' }
    useTimeRange(params)
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toEqual(params)
  })

  it('test_useTimeRange_fetcher_callsApiLibraryImageTimeRangeWithParams', async () => {
    const params = { tags: ['tag1'], source: 'ehentai' }
    useTimeRange(params)
    await lastSwrCall().fetcher!()
    expect(mockImageTimeRange).toHaveBeenCalledOnce()
    expect(mockImageTimeRange).toHaveBeenCalledWith(params)
  })

  it('test_useTimeRange_options_setsDedupingIntervalTo300000_regressionUnnecessaryRefetches', () => {
    // Regression: missing dedupingInterval caused the hook to refetch on every render
    // because useSWR defaults to 2000ms deduplication, which is too short for a
    // time-range query that rarely changes. 300_000ms (5 min) prevents spamming the API.
    useTimeRange()
    expect(lastSwrCall().options.dedupingInterval).toBe(300_000)
  })

  it('test_useTimeRange_options_setsRevalidateOnFocusFalse', () => {
    useTimeRange()
    expect(lastSwrCall().options.revalidateOnFocus).toBe(false)
  })

  it('test_useTimeRange_withNoData_returnsNullMinAtAndMaxAt', () => {
    const result = useTimeRange()
    expect(result.minAt).toBeNull()
    expect(result.maxAt).toBeNull()
  })

  it('test_useTimeRange_withData_returnsDateObjects', () => {
    const minStr = '2023-01-01T00:00:00Z'
    const maxStr = '2024-06-01T00:00:00Z'
    mockUseSWR.mockReturnValueOnce({
      data: { min_at: minStr, max_at: maxStr } as { min_at: string; max_at: string },
      error: undefined,
    } as unknown as ReturnType<typeof mockUseSWR>)
    const result = useTimeRange()
    expect(result.minAt).toEqual(new Date(minStr))
    expect(result.maxAt).toEqual(new Date(maxStr))
  })
})
