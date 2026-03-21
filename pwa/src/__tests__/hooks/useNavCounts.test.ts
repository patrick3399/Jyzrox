/**
 * useNavCounts — Vitest test suite
 *
 * Covers:
 *   useNavCounts — returns zero counts when SWR data is undefined
 *   useNavCounts — returns correct counts when SWR resolves data
 *   useNavCounts — calls useSWR with the correct keys
 *   useNavCounts — SWR config includes refreshInterval: 30000
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted SWR capture ────────────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

// Per-key data map so each call can return independent data.
let swrDataMap: Record<string, unknown> = {}

const { mockUseSWR } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

// ── api mock (fetchers are not exercised directly here) ────────────────

vi.mock('@/lib/api', () => ({
  api: {
    library: { getGalleries: vi.fn() },
    subscriptions: { list: vi.fn() },
    collections: { list: vi.fn() },
  },
}))

// ── Import hook after mocks ────────────────────────────────────────────

import { useNavCounts } from '@/hooks/useNavCounts'

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  swrCalls.length = 0
  swrDataMap = {}

  mockUseSWR.mockImplementation(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: swrDataMap[key as string], isLoading: false, error: undefined }
    },
  )
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Helpers ────────────────────────────────────────────────────────────

function swrCallForKey(key: string): SwrCall | undefined {
  return swrCalls.find((c) => c.key === key)
}

// ── Tests ──────────────────────────────────────────────────────────────

describe('useNavCounts', () => {
  describe('zero counts (SWR data undefined)', () => {
    it('test_useNavCounts_undefinedData_libraryCountIsZero', () => {
      const result = useNavCounts()
      expect(result['/library']).toBe(0)
    })

    it('test_useNavCounts_undefinedData_subscriptionsCountIsZero', () => {
      const result = useNavCounts()
      expect(result['/subscriptions']).toBe(0)
    })

    it('test_useNavCounts_undefinedData_collectionsCountIsZero', () => {
      const result = useNavCounts()
      expect(result['/collections']).toBe(0)
    })

    it('test_useNavCounts_undefinedData_returnsFullZeroObject', () => {
      const result = useNavCounts()
      expect(result).toEqual({
        '/library': 0,
        '/subscriptions': 0,
        '/collections': 0,
      })
    })
  })

  describe('correct counts when SWR resolves data', () => {
    it('test_useNavCounts_libraryData_returnsLibraryTotal', () => {
      swrDataMap['nav-counts/library'] = { total: 42 }
      const result = useNavCounts()
      expect(result['/library']).toBe(42)
    })

    it('test_useNavCounts_subscriptionsData_returnsSubscriptionsTotal', () => {
      swrDataMap['nav-counts/subscriptions'] = { total: 7 }
      const result = useNavCounts()
      expect(result['/subscriptions']).toBe(7)
    })

    it('test_useNavCounts_collectionsData_returnsCollectionsLength', () => {
      swrDataMap['nav-counts/collections'] = {
        collections: [{ id: 1 }, { id: 2 }, { id: 3 }],
      }
      const result = useNavCounts()
      expect(result['/collections']).toBe(3)
    })

    it('test_useNavCounts_allDataPresent_returnsCombinedCounts', () => {
      swrDataMap['nav-counts/library'] = { total: 10 }
      swrDataMap['nav-counts/subscriptions'] = { total: 5 }
      swrDataMap['nav-counts/collections'] = { collections: [{ id: 1 }] }
      const result = useNavCounts()
      expect(result).toEqual({
        '/library': 10,
        '/subscriptions': 5,
        '/collections': 1,
      })
    })

    it('test_useNavCounts_emptyCollectionsArray_returnsZero', () => {
      swrDataMap['nav-counts/collections'] = { collections: [] }
      const result = useNavCounts()
      expect(result['/collections']).toBe(0)
    })
  })

  describe('correct SWR keys', () => {
    it('test_useNavCounts_keys_usesNavCountsLibraryKey', () => {
      useNavCounts()
      expect(swrCallForKey('nav-counts/library')).toBeDefined()
    })

    it('test_useNavCounts_keys_usesNavCountsSubscriptionsKey', () => {
      useNavCounts()
      expect(swrCallForKey('nav-counts/subscriptions')).toBeDefined()
    })

    it('test_useNavCounts_keys_usesNavCountsCollectionsKey', () => {
      useNavCounts()
      expect(swrCallForKey('nav-counts/collections')).toBeDefined()
    })

    it('test_useNavCounts_keys_callsUseSWRThreeTimes', () => {
      useNavCounts()
      expect(mockUseSWR).toHaveBeenCalledTimes(3)
    })
  })

  describe('SWR config options', () => {
    it('test_useNavCounts_config_libraryHasRefreshInterval30000', () => {
      useNavCounts()
      const call = swrCallForKey('nav-counts/library')
      expect(call?.options.refreshInterval).toBe(30000)
    })

    it('test_useNavCounts_config_subscriptionsHasRefreshInterval30000', () => {
      useNavCounts()
      const call = swrCallForKey('nav-counts/subscriptions')
      expect(call?.options.refreshInterval).toBe(30000)
    })

    it('test_useNavCounts_config_collectionsHasRefreshInterval30000', () => {
      useNavCounts()
      const call = swrCallForKey('nav-counts/collections')
      expect(call?.options.refreshInterval).toBe(30000)
    })

    it('test_useNavCounts_config_allCallsHaveRevalidateOnFocusFalse', () => {
      useNavCounts()
      for (const call of swrCalls) {
        expect(call.options.revalidateOnFocus).toBe(false)
      }
    })
  })

  describe('enabled=false skips fetching (null SWR keys)', () => {
    it('test_useNavCounts_disabledEnabled_libraryKeyIsNull', () => {
      useNavCounts(false)
      const nullCalls = swrCalls.filter((c) => c.key === null)
      expect(nullCalls).toHaveLength(3)
    })

    it('test_useNavCounts_disabledEnabled_noStringKeysRegistered', () => {
      useNavCounts(false)
      expect(swrCallForKey('nav-counts/library')).toBeUndefined()
      expect(swrCallForKey('nav-counts/subscriptions')).toBeUndefined()
      expect(swrCallForKey('nav-counts/collections')).toBeUndefined()
    })

    it('test_useNavCounts_disabledEnabled_returnsAllZeroCounts', () => {
      useNavCounts(false)
      const result = useNavCounts(false)
      expect(result).toEqual({
        '/library': 0,
        '/subscriptions': 0,
        '/collections': 0,
      })
    })

    it('test_useNavCounts_enabledTrueByDefault_usesStringKeys', () => {
      useNavCounts()
      expect(swrCallForKey('nav-counts/library')).toBeDefined()
      expect(swrCallForKey('nav-counts/subscriptions')).toBeDefined()
      expect(swrCallForKey('nav-counts/collections')).toBeDefined()
    })
  })
})
