/**
 * useGalleries — Vitest test suite
 *
 * Covers:
 *   useLibraryGalleries — passes correct SWR key and fetches via api.library.getGalleries
 *   useLibraryGallery   — passes null key when id is null; correct key and fetch when id given
 *   useGalleryImages    — passes null key when id is null; correct key and fetch when id given
 *   useEhSearch         — passes key ['eh/search', params] and revalidateOnFocus: false
 *   useEhPopular        — passes key 'eh/popular' and revalidateOnFocus: false
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations. Variables used inside
 *   a factory must be created with vi.hoisted() to be available at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const {
  mockGetGalleries,
  mockGetGallery,
  mockGetImages,
  mockGetProgress,
  mockEhSearch,
  mockEhGetPopular,
} = vi.hoisted(() => ({
  mockGetGalleries: vi.fn(),
  mockGetGallery: vi.fn(),
  mockGetImages: vi.fn(),
  mockGetProgress: vi.fn(),
  mockEhSearch: vi.fn(),
  mockEhGetPopular: vi.fn(),
}))

// ── api mock ──────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      getGalleries: mockGetGalleries,
      getGallery: mockGetGallery,
      getImages: mockGetImages,
      getProgress: mockGetProgress,
    },
    eh: {
      search: mockEhSearch,
      getPopular: mockEhGetPopular,
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
  useLibraryGalleries,
  useLibraryGallery,
  useGalleryImages,
  useGalleryProgress,
  useEhSearch,
  useEhPopular,
} from '@/hooks/useGalleries'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockGetGalleries.mockResolvedValue({ galleries: [], total: 0 })
  mockGetGallery.mockResolvedValue({ id: 1, title: 'Test Gallery' })
  mockGetImages.mockResolvedValue([])
  mockGetProgress.mockResolvedValue({ page: 1 })
  mockEhSearch.mockResolvedValue({ galleries: [] })
  mockEhGetPopular.mockResolvedValue([])
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useLibraryGalleries', () => {
  it('test_useLibraryGalleries_noParams_callsUseSWROnce', () => {
    useLibraryGalleries()
    expect(mockUseSWR).toHaveBeenCalledOnce()
  })

  it('test_useLibraryGalleries_noParams_keyFirstElementIsLibraryGalleries', () => {
    useLibraryGalleries()
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('library/galleries')
  })

  it('test_useLibraryGalleries_noParams_keySecondElementIsZeroWhenNoCursor', () => {
    // Neither cursor nor page provided → should degrade to 0
    useLibraryGalleries()
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toBe(0)
  })

  it('test_useLibraryGalleries_withPage_keySecondElementMatchesPage', () => {
    useLibraryGalleries({ page: 3 })
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toBe(3)
  })

  it('test_useLibraryGalleries_withCursor_keySecondElementMatchesCursor', () => {
    useLibraryGalleries({ cursor: 'cursor-xyz' })
    const { key } = lastSwrCall()
    // cursor takes precedence over page
    expect((key as unknown[])[1]).toBe('cursor-xyz')
  })

  it('test_useLibraryGalleries_fetcher_callsApiLibraryGetGalleriesWithParams', async () => {
    const params = { q: 'touhou', page: 1 }
    useLibraryGalleries(params)
    await lastSwrCall().fetcher!()
    expect(mockGetGalleries).toHaveBeenCalledOnce()
    expect(mockGetGalleries).toHaveBeenCalledWith(params)
  })

  it('test_useLibraryGalleries_returnsSwrResult', () => {
    const result = useLibraryGalleries()
    expect(result).toMatchObject({ data: undefined, isLoading: true })
  })
})

describe('useLibraryGallery', () => {
  it('test_useLibraryGallery_withNullId_passesNullKeyToSWR', () => {
    useLibraryGallery(null, null)
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useLibraryGallery_withId_keyFirstElementIsLibraryGallery', () => {
    useLibraryGallery('ehentai', '42')
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('library/gallery')
  })

  it('test_useLibraryGallery_withId_keySecondElementMatchesId', () => {
    useLibraryGallery('ehentai', '42')
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toBe('ehentai')
  })

  it('test_useLibraryGallery_withId_fetcher_callsApiLibraryGetGalleryWithId', async () => {
    useLibraryGallery('ehentai', '42')
    await lastSwrCall().fetcher!()
    expect(mockGetGallery).toHaveBeenCalledOnce()
    expect(mockGetGallery).toHaveBeenCalledWith('ehentai', '42')
  })

  it('test_useLibraryGallery_withNullId_fetcher_notCalledByDefault', async () => {
    useLibraryGallery(null, null)
    // The fetcher exists but api.library.getGallery should never be invoked
    // because SWR skips fetching when key is null.
    expect(mockGetGallery).not.toHaveBeenCalled()
  })
})

describe('useGalleryImages', () => {
  it('test_useGalleryImages_withNullId_passesNullKeyToSWR', () => {
    useGalleryImages(null, null)
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useGalleryImages_withId_keyFirstElementIsGalleryImages', () => {
    useGalleryImages('ehentai', '7')
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('gallery/images')
  })

  it('test_useGalleryImages_withId_keySecondElementMatchesSource', () => {
    useGalleryImages('ehentai', '7')
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toBe('ehentai')
  })

  it('test_useGalleryImages_withId_fetcher_callsApiLibraryGetImagesWithSourceAndId', async () => {
    useGalleryImages('ehentai', '7')
    await lastSwrCall().fetcher!()
    expect(mockGetImages).toHaveBeenCalledOnce()
    expect(mockGetImages).toHaveBeenCalledWith('ehentai', '7')
  })
})

describe('useGalleryProgress', () => {
  it('test_useGalleryProgress_withNullId_passesNullKeyToSWR', () => {
    useGalleryProgress(null, null)
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useGalleryProgress_withId_keyFirstElementIsGalleryProgress', () => {
    useGalleryProgress('ehentai', '5')
    const { key } = lastSwrCall()
    expect((key as unknown[])[0]).toBe('gallery/progress')
  })

  it('test_useGalleryProgress_withId_fetcher_callsApiLibraryGetProgressWithSourceAndId', async () => {
    useGalleryProgress('ehentai', '5')
    await lastSwrCall().fetcher!()
    expect(mockGetProgress).toHaveBeenCalledWith('ehentai', '5')
  })
})

describe('useEhSearch', () => {
  it('test_useEhSearch_keyFirstElementIsEhSearch', () => {
    useEhSearch({ q: 'touhou' })
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('eh/search')
  })

  it('test_useEhSearch_keySecondElementIsTheParamsObject', () => {
    const params = { q: 'touhou' }
    useEhSearch(params)
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toEqual(params)
  })

  it('test_useEhSearch_configuredWithRevalidateOnFocusFalse', () => {
    useEhSearch({})
    expect(lastSwrCall().options.revalidateOnFocus).toBe(false)
  })

  it('test_useEhSearch_fetcher_callsApiEhSearchWithParams', async () => {
    const params = { q: 'reimu' }
    useEhSearch(params)
    await lastSwrCall().fetcher!()
    expect(mockEhSearch).toHaveBeenCalledWith(params)
  })
})

describe('useEhPopular', () => {
  it('test_useEhPopular_keyIsEhPopularString', () => {
    useEhPopular()
    expect(lastSwrCall().key).toBe('eh/popular')
  })

  it('test_useEhPopular_configuredWithRevalidateOnFocusFalse', () => {
    useEhPopular()
    expect(lastSwrCall().options.revalidateOnFocus).toBe(false)
  })

  it('test_useEhPopular_fetcher_callsApiEhGetPopular', async () => {
    useEhPopular()
    await lastSwrCall().fetcher!()
    expect(mockEhGetPopular).toHaveBeenCalledOnce()
  })
})
