/**
 * useDedup — Vitest test suite
 *
 * Covers:
 *   useDedupStats          — passes key 'dedup-stats' with refreshInterval: 30000
 *   useDedupStats          — fetcher calls api.dedup.getStats
 *   useDedupSettings       — passes key 'dedup-features'
 *   useDedupSettings       — fetcher calls api.settings.getFeatures
 *   useUpdateDedupSetting  — trigger calls api.settings.setFeature with feature and enabled
 *   useUpdateDedupThreshold — trigger calls api.settings.setFeatureValue with threshold
 *   useDedupScanProgress   — passes key 'dedup-scan-progress'
 *   useDedupScanProgress   — startScan calls api.dedup.startScan and mutate
 *   useDedupScanProgress   — sendSignal calls api.dedup.sendSignal and mutate
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const {
  mockGetStats,
  mockGetFeatures,
  mockSetFeature,
  mockSetFeatureValue,
  mockGetScanProgress,
  mockStartScan,
  mockSendSignal,
  mockGetReview,
} = vi.hoisted(() => ({
  mockGetStats: vi.fn(),
  mockGetFeatures: vi.fn(),
  mockSetFeature: vi.fn(),
  mockSetFeatureValue: vi.fn(),
  mockGetScanProgress: vi.fn(),
  mockStartScan: vi.fn(),
  mockSendSignal: vi.fn(),
  mockGetReview: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    dedup: {
      getStats: mockGetStats,
      getScanProgress: mockGetScanProgress,
      startScan: mockStartScan,
      sendSignal: mockSendSignal,
      getReview: mockGetReview,
    },
    settings: {
      getFeatures: mockGetFeatures,
      setFeature: mockSetFeature,
      setFeatureValue: mockSetFeatureValue,
    },
  },
}))

// ── React mock — stub useState, useCallback, useRef to avoid hook context errors ─

vi.mock('react', async () => {
  const actual = await vi.importActual<typeof import('react')>('react')
  return {
    ...actual,
    useRef: () => ({ current: undefined }),
    useEffect: vi.fn(),
  }
})

// ── swr / swr/mutation mocks ──────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
  mutateFn?: () => void
}

const swrCalls: SwrCall[] = []
const mockMutate = vi.fn()

const { mockUseSWR, mockUseSWRMutation } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: false, error: undefined, mutate: mockMutate }
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

import {
  useDedupStats,
  useDedupSettings,
  useUpdateDedupSetting,
  useUpdateDedupThreshold,
  useDedupScanProgress,
} from '@/hooks/useDedup'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockGetStats.mockResolvedValue({ total: 0, duplicates: 0 })
  mockGetFeatures.mockResolvedValue({ dedup_enabled: true })
  mockSetFeature.mockResolvedValue({})
  mockSetFeatureValue.mockResolvedValue({})
  mockGetScanProgress.mockResolvedValue({ status: 'idle' })
  mockStartScan.mockResolvedValue({})
  mockSendSignal.mockResolvedValue({})
  mockGetReview.mockResolvedValue({ items: [], next_cursor: null })
})

afterEach(() => {
  vi.clearAllMocks()
})

function swrCallForKey(key: string): SwrCall | undefined {
  return swrCalls.find((c) => c.key === key)
}

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useDedupStats', () => {
  it('test_useDedupStats_key_isDedupStatsString', () => {
    useDedupStats()
    expect(lastSwrCall().key).toBe('dedup-stats')
  })

  it('test_useDedupStats_options_setsRefreshInterval30000', () => {
    useDedupStats()
    expect(lastSwrCall().options.refreshInterval).toBe(30000)
  })

  it('test_useDedupStats_fetcher_callsApiDedupGetStats', async () => {
    useDedupStats()
    await lastSwrCall().fetcher!()
    expect(mockGetStats).toHaveBeenCalledOnce()
  })
})

describe('useDedupSettings', () => {
  it('test_useDedupSettings_key_isDedupFeaturesString', () => {
    useDedupSettings()
    expect(lastSwrCall().key).toBe('dedup-features')
  })

  it('test_useDedupSettings_fetcher_callsApiSettingsGetFeatures', async () => {
    useDedupSettings()
    await lastSwrCall().fetcher!()
    expect(mockGetFeatures).toHaveBeenCalledOnce()
  })
})

describe('useUpdateDedupSetting', () => {
  it('test_useUpdateDedupSetting_key_isDedupFeaturesString', () => {
    useUpdateDedupSetting()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('dedup-features')
  })

  it('test_useUpdateDedupSetting_trigger_callsApiSettingsSetFeatureWithArgs', async () => {
    const { trigger } = useUpdateDedupSetting()
    await trigger({ feature: 'dedup_enabled', enabled: false })
    expect(mockSetFeature).toHaveBeenCalledWith('dedup_enabled', false)
  })
})

describe('useUpdateDedupThreshold', () => {
  it('test_useUpdateDedupThreshold_key_isDedupFeaturesString', () => {
    useUpdateDedupThreshold()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('dedup-features')
  })

  it('test_useUpdateDedupThreshold_trigger_callsSetFeatureValueWithThreshold', async () => {
    const { trigger } = useUpdateDedupThreshold()
    await trigger(12)
    expect(mockSetFeatureValue).toHaveBeenCalledWith('dedup_phash_threshold', 12)
  })
})

describe('useDedupScanProgress', () => {
  it('test_useDedupScanProgress_key_isDedupScanProgressString', () => {
    useDedupScanProgress()
    const call = swrCallForKey('dedup-scan-progress')
    expect(call).toBeDefined()
  })

  it('test_useDedupScanProgress_options_setsRevalidateOnFocusFalse', () => {
    useDedupScanProgress()
    const call = swrCallForKey('dedup-scan-progress')
    expect(call?.options.revalidateOnFocus).toBe(false)
  })

  it('test_useDedupScanProgress_startScan_callsApiDedupStartScan', async () => {
    const { startScan } = useDedupScanProgress()
    await startScan('reset')
    expect(mockStartScan).toHaveBeenCalledWith('reset')
  })

  it('test_useDedupScanProgress_sendSignal_callsApiDedupSendSignal', async () => {
    const { sendSignal } = useDedupScanProgress()
    await sendSignal('pause')
    expect(mockSendSignal).toHaveBeenCalledWith('pause')
  })
})
