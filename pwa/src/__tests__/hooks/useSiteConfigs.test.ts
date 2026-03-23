/**
 * useSiteConfigs — Vitest test suite
 *
 * Covers:
 *   useSiteConfigs         — passes 'admin-sites' key to useSWR
 *   useSiteConfigs         — fetcher calls api.adminSites.list
 *   useProbe               — passes 'admin-sites-probe' key to useSWRMutation
 *   useProbe               — trigger calls api.adminSites.probe with URL arg
 *   useUpdateSiteConfig    — trigger calls api.adminSites.update with sourceId and data
 *   useUpdateFieldMapping  — trigger calls api.adminSites.updateFieldMapping
 *   useResetSiteField      — trigger calls api.adminSites.reset
 *   useResetAdaptive       — trigger calls api.adminSites.resetAdaptive
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockList, mockProbe, mockUpdate, mockUpdateFieldMapping, mockReset, mockResetAdaptive } =
  vi.hoisted(() => ({
    mockList: vi.fn(),
    mockProbe: vi.fn(),
    mockUpdate: vi.fn(),
    mockUpdateFieldMapping: vi.fn(),
    mockReset: vi.fn(),
    mockResetAdaptive: vi.fn(),
  }))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    adminSites: {
      list: mockList,
      probe: mockProbe,
      update: mockUpdate,
      updateFieldMapping: mockUpdateFieldMapping,
      reset: mockReset,
      resetAdaptive: mockResetAdaptive,
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

import {
  useSiteConfigs,
  useProbe,
  useUpdateSiteConfig,
  useUpdateFieldMapping,
  useResetSiteField,
  useResetAdaptive,
} from '@/hooks/useSiteConfigs'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockList.mockResolvedValue([])
  mockProbe.mockResolvedValue({ status: 'ok' })
  mockUpdate.mockResolvedValue({})
  mockUpdateFieldMapping.mockResolvedValue({})
  mockReset.mockResolvedValue({})
  mockResetAdaptive.mockResolvedValue({})
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useSiteConfigs', () => {
  it('test_useSiteConfigs_key_isAdminSites', () => {
    useSiteConfigs()
    expect(lastSwrCall().key).toBe('admin-sites')
  })

  it('test_useSiteConfigs_fetcher_callsApiAdminSitesList', async () => {
    useSiteConfigs()
    await lastSwrCall().fetcher!()
    expect(mockList).toHaveBeenCalledOnce()
  })
})

describe('useProbe', () => {
  it('test_useProbe_key_isAdminSitesProbe', () => {
    useProbe()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('admin-sites-probe')
  })

  it('test_useProbe_trigger_callsApiAdminSitesProbeWithUrl', async () => {
    const { trigger } = useProbe()
    await trigger('https://example.com')
    expect(mockProbe).toHaveBeenCalledWith('https://example.com')
  })
})

describe('useUpdateSiteConfig', () => {
  it('test_useUpdateSiteConfig_key_isAdminSites', () => {
    useUpdateSiteConfig()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('admin-sites')
  })

  it('test_useUpdateSiteConfig_trigger_callsApiAdminSitesUpdateWithSourceIdAndData', async () => {
    const { trigger } = useUpdateSiteConfig()
    const arg = { sourceId: 'pixiv', data: { download: { max_posts: 100 } } }
    await trigger(arg)
    expect(mockUpdate).toHaveBeenCalledWith('pixiv', { download: { max_posts: 100 } })
  })
})

describe('useUpdateFieldMapping', () => {
  it('test_useUpdateFieldMapping_key_isAdminSites', () => {
    useUpdateFieldMapping()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('admin-sites')
  })

  it('test_useUpdateFieldMapping_trigger_callsApiAdminSitesUpdateFieldMapping', async () => {
    const { trigger } = useUpdateFieldMapping()
    const arg = { sourceId: 'pixiv', fieldMapping: { title: 'caption', tags: null } }
    await trigger(arg)
    expect(mockUpdateFieldMapping).toHaveBeenCalledWith('pixiv', { title: 'caption', tags: null })
  })
})

describe('useResetSiteField', () => {
  it('test_useResetSiteField_key_isAdminSites', () => {
    useResetSiteField()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('admin-sites')
  })

  it('test_useResetSiteField_trigger_callsApiAdminSitesResetWithSourceIdAndFieldPath', async () => {
    const { trigger } = useResetSiteField()
    await trigger({ sourceId: 'pixiv', fieldPath: 'download.max_posts' })
    expect(mockReset).toHaveBeenCalledWith('pixiv', 'download.max_posts')
  })
})

describe('useResetAdaptive', () => {
  it('test_useResetAdaptive_key_isAdminSites', () => {
    useResetAdaptive()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('admin-sites')
  })

  it('test_useResetAdaptive_trigger_callsApiAdminSitesResetAdaptiveWithSourceId', async () => {
    const { trigger } = useResetAdaptive()
    await trigger('pixiv')
    expect(mockResetAdaptive).toHaveBeenCalledWith('pixiv')
  })
})
