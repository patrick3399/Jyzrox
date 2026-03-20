/**
 * useImport — Vitest test suite
 *
 * Covers:
 *   useImportProgress   — null galleryId passes null key; valid id passes array key
 *   useBatchScan        — trigger calls api.import_.batchScan with rootDir and pattern
 *   useBatchStart       — trigger calls api.import_.batchStart with galleries
 *   useRescanLibrary    — trigger calls api.import_.rescan
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const {
  mockProgress,
  mockBatchScan,
  mockBatchStart,
  mockBatchProgress,
  mockRescanLibraryPath,
  mockRescan,
  mockRescanStatus,
  mockLibraries,
  mockMonitorStatus,
  mockAddLibrary,
  mockRemoveLibrary,
  mockRescanCancel,
  mockBrowseFs,
  mockMountPoints,
  mockToggleMonitor,
} = vi.hoisted(() => ({
  mockProgress: vi.fn(),
  mockBatchScan: vi.fn(),
  mockBatchStart: vi.fn(),
  mockBatchProgress: vi.fn(),
  mockRescanLibraryPath: vi.fn(),
  mockRescan: vi.fn(),
  mockRescanStatus: vi.fn(),
  mockLibraries: vi.fn(),
  mockMonitorStatus: vi.fn(),
  mockAddLibrary: vi.fn(),
  mockRemoveLibrary: vi.fn(),
  mockRescanCancel: vi.fn(),
  mockBrowseFs: vi.fn(),
  mockMountPoints: vi.fn(),
  mockToggleMonitor: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    import_: {
      progress: mockProgress,
      batchScan: mockBatchScan,
      batchStart: mockBatchStart,
      batchProgress: mockBatchProgress,
      rescanLibraryPath: mockRescanLibraryPath,
      rescan: mockRescan,
      rescanStatus: mockRescanStatus,
      libraries: mockLibraries,
      monitorStatus: mockMonitorStatus,
      addLibrary: mockAddLibrary,
      removeLibrary: mockRemoveLibrary,
      rescanCancel: mockRescanCancel,
      browseFs: mockBrowseFs,
      mountPoints: mockMountPoints,
      toggleMonitor: mockToggleMonitor,
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

const { mockUseSWR, mockUseSWRMutation, mockUseSWRConfig } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: false, error: undefined }
    },
  ),
  mockUseSWRMutation: vi.fn(
    (_key: unknown, fetcher: (_k: unknown, extra: { arg: unknown }) => unknown) => ({
      trigger: (arg: unknown) => fetcher(_key, { arg }),
      isMutating: false,
    }),
  ),
  mockUseSWRConfig: vi.fn(() => ({ mutate: vi.fn() })),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  useSWRConfig: mockUseSWRConfig,
  mutate: vi.fn(),
}))

vi.mock('swr/mutation', () => ({
  default: mockUseSWRMutation,
}))

// ── Import hooks after mocks ──────────────────────────────────────────

import { useImportProgress, useBatchScan, useBatchStart, useRescanLibrary } from '@/hooks/useImport'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockProgress.mockResolvedValue({ status: 'idle' })
  mockBatchScan.mockResolvedValue({ galleries: [] })
  mockBatchStart.mockResolvedValue({ batch_id: 'abc' })
  mockRescan.mockResolvedValue({})
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useImportProgress', () => {
  it('test_useImportProgress_nullGalleryId_passesNullKeyToSwr', () => {
    useImportProgress(null)
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useImportProgress_validGalleryId_passesArrayKeyWithId', () => {
    useImportProgress(42)
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('import/progress')
    expect((key as unknown[])[1]).toBe(42)
  })

  it('test_useImportProgress_options_setsRefreshInterval2000', () => {
    useImportProgress(1)
    expect(lastSwrCall().options.refreshInterval).toBe(2000)
  })
})

describe('useBatchScan', () => {
  it('test_useBatchScan_key_isImportBatchScanString', () => {
    useBatchScan()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('import/batch/scan')
  })

  it('test_useBatchScan_trigger_callsApiBatchScanWithRootDirAndPattern', async () => {
    const { trigger } = useBatchScan()
    await trigger({ rootDir: '/mnt/art', pattern: '**/*.jpg' })
    expect(mockBatchScan).toHaveBeenCalledWith('/mnt/art', '**/*.jpg')
  })
})

describe('useBatchStart', () => {
  it('test_useBatchStart_key_isImportBatchStartString', () => {
    useBatchStart()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('import/batch/start')
  })

  it('test_useBatchStart_trigger_callsApiBatchStartWithArgs', async () => {
    const { trigger } = useBatchStart()
    const galleries = [{ path: '/mnt/art/g1', artist: 'Alice', title: 'Gallery 1' }]
    await trigger({ rootDir: '/mnt/art', mode: 'copy', galleries })
    expect(mockBatchStart).toHaveBeenCalledWith('/mnt/art', 'copy', galleries)
  })
})

describe('useRescanLibrary', () => {
  it('test_useRescanLibrary_key_isImportRescanString', () => {
    useRescanLibrary()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('import/rescan')
  })

  it('test_useRescanLibrary_trigger_callsApiImportRescan', async () => {
    const { trigger } = useRescanLibrary()
    await trigger(undefined)
    expect(mockRescan).toHaveBeenCalledOnce()
  })
})
