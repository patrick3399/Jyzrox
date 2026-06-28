/**
 * useArtists — Vitest test suite
 *
 * Covers:
 *   useArtists        — passes key ['artists', JSON.stringify(params)] to useSWR
 *   useArtists        — fetcher calls api.library.getArtists with params
 *   useArtistSummary  — passes null key when artistId is empty string
 *   useArtistSummary  — passes array key with artistId when non-empty
 *   useArtistImages   — passes null key when artistId is empty; array key otherwise
 *   useArtistImages   — fetcher calls api.library.getArtistImages with artistId and params
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockGetArtists, mockGetArtistSummary, mockGetArtistImages } = vi.hoisted(() => ({
  mockGetArtists: vi.fn(),
  mockGetArtistSummary: vi.fn(),
  mockGetArtistImages: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      getArtists: mockGetArtists,
      getArtistSummary: mockGetArtistSummary,
      getArtistImages: mockGetArtistImages,
    },
  },
}))

// ── swr mock ─────────────────────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: ((...args: unknown[]) => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

const { mockUseSWR } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: ((...args: unknown[]) => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: true, error: undefined }
    },
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

// ── Import hooks after mocks ──────────────────────────────────────────

import { useArtists, useArtistSummary, useArtistImages } from '@/hooks/useArtists'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockGetArtists.mockResolvedValue({ artists: [], total: 0 })
  mockGetArtistSummary.mockResolvedValue({ id: '1', name: 'Test' })
  mockGetArtistImages.mockResolvedValue({ images: [], total: 0 })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useArtists', () => {
  it('test_useArtists_key_firstElementIsArtistsString', () => {
    useArtists()
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('artists')
  })

  it('test_useArtists_key_secondElementIsJsonStringifiedParams', () => {
    const params = { q: 'alice', source: 'pixiv' }
    useArtists(params)
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toBe(JSON.stringify(params))
  })

  it('test_useArtists_fetcher_callsApiLibraryGetArtistsWithParams', async () => {
    const params = { sort: 'name', page: 2 }
    useArtists(params)
    await lastSwrCall().fetcher!()
    // fetcher forwards the SWR AbortSignal (undefined when invoked bare)
    expect(mockGetArtists).toHaveBeenCalledWith(params, { signal: undefined })
  })
})

describe('useArtistSummary', () => {
  it('test_useArtistSummary_emptyArtistId_passesNullKeyToSwr', () => {
    useArtistSummary('')
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useArtistSummary_validArtistId_passesArrayKeyWithId', () => {
    useArtistSummary('pixiv:123')
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('artist-summary')
    expect((key as unknown[])[1]).toBe('pixiv:123')
  })

  it('test_useArtistSummary_fetcher_callsApiLibraryGetArtistSummary', async () => {
    useArtistSummary('pixiv:456')
    // fetcher destructures the SWR key for the id
    await lastSwrCall().fetcher!(['artist-summary', 'pixiv:456'])
    expect(mockGetArtistSummary).toHaveBeenCalledWith('pixiv:456', { signal: undefined })
  })
})

describe('useArtistImages', () => {
  it('test_useArtistImages_emptyArtistId_passesNullKeyToSwr', () => {
    useArtistImages('')
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useArtistImages_validArtistId_passesArrayKeyWithId', () => {
    useArtistImages('eh:789')
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('artist-images')
    expect((key as unknown[])[1]).toBe('eh:789')
  })

  it('test_useArtistImages_fetcher_callsApiLibraryGetArtistImagesWithArtistIdAndParams', async () => {
    const params = { page: 1, limit: 50, sort: 'newest' as const }
    useArtistImages('pixiv:999', params)
    // fetcher destructures the SWR key for the id; params come from the closure
    await lastSwrCall().fetcher!(['artist-images', 'pixiv:999', JSON.stringify(params)])
    expect(mockGetArtistImages).toHaveBeenCalledWith('pixiv:999', params, { signal: undefined })
  })
})
