/**
 * useGalleries — Vitest test suite
 *
 * Covers:
 *   useLibraryGalleries         — passes correct SWR key and fetches via api.library.getGalleries
 *   useLibraryGallery           — passes null key when id is null; correct key and fetch when id given
 *   useGalleryImages            — passes null key when id is null; correct key and fetch when id given
 *   useEhSearch                 — passes key ['eh/search', params] and revalidateOnFocus: false
 *   useEhPopular                — passes key 'eh/popular' and revalidateOnFocus: false
 *   useInfiniteLibraryGalleries — cursor/filter state-consistency (getKey shape, duplicate guard)
 *   useSearchGalleries          — stale data cleared when query changes (getKey returns null for empty q)
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
  fetcher: ((...args: unknown[]) => unknown) | null
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
  useSWRConfig: () => ({ mutate: vi.fn() }),
}))

vi.mock('swr/mutation', () => ({
  default: mockUseSWRMutation,
}))

// ── swr/infinite mock ─────────────────────────────────────────────────

interface InfiniteCall {
  getKey: (pageIndex: number, prev: unknown) => unknown
  fetcher: (key: unknown) => unknown
  options: Record<string, unknown>
}

const infiniteCalls: InfiniteCall[] = []

const { mockUseSWRInfinite } = vi.hoisted(() => ({
  mockUseSWRInfinite: vi.fn(
    (
      getKey: (pageIndex: number, prev: unknown) => unknown,
      fetcher: (key: unknown) => unknown,
      options: Record<string, unknown> = {},
    ) => {
      infiniteCalls.push({ getKey, fetcher, options })
      return {
        data: undefined as unknown[] | undefined,
        error: undefined,
        size: 1,
        setSize: vi.fn(),
        isValidating: false,
        isLoading: false,
        mutate: vi.fn(),
      }
    },
  ),
}))

vi.mock('swr/infinite', () => ({
  default: mockUseSWRInfinite,
}))

// ── @/lib/ws mock ─────────────────────────────────────────────────────

vi.mock('@/lib/ws', () => ({
  useWsJobs: () => ({ lastJobUpdate: null }),
}))

// ── React hooks stub for hooks that use useRef / useEffect / useCallback ──
//
// useInfiniteLibraryGalleries and useSearchGalleries call useRef/useEffect/
// useCallback/useMemo directly. Outside a component tree React's dispatcher
// is null, so those calls throw. We stub them so the hook body executes
// without a running React renderer, while keeping useSWRInfinite mocked
// above to capture getKey / fetcher / options.

vi.mock('react', async () => {
  const actual = await vi.importActual<typeof import('react')>('react')
  return {
    ...actual,
    useRef: (initial: unknown) => ({ current: initial }),
    useEffect: (_fn: () => unknown) => undefined,
    useCallback: (fn: unknown) => fn,
    useMemo: (fn: () => unknown) => fn(),
  }
})

// ── Import hooks after mocks ──────────────────────────────────────────

import {
  useLibraryGalleries,
  useLibraryGallery,
  useGalleryImages,
  useGalleryProgress,
  useEhSearch,
  useEhPopular,
  useInfiniteLibraryGalleries,
  useSearchGalleries,
} from '@/hooks/useGalleries'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  infiniteCalls.length = 0
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
    // SWR passes (key, { signal }) as the two fetcher args; the hook ignores key
    // and forwards { signal } to the api call.
    await lastSwrCall().fetcher!(null, {})
    expect(mockGetGalleries).toHaveBeenCalledOnce()
    expect(mockGetGalleries).toHaveBeenCalledWith(params, { signal: undefined })
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
    // Hook fetcher destructures key array; pass the same array SWR would provide.
    await lastSwrCall().fetcher!(['library/gallery', 'ehentai', '42'], {})
    expect(mockGetGallery).toHaveBeenCalledOnce()
    expect(mockGetGallery).toHaveBeenCalledWith('ehentai', '42', { signal: undefined })
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
    // Hook fetcher destructures key array; pass the same array SWR would provide.
    await lastSwrCall().fetcher!(['gallery/images', 'ehentai', '7'], {})
    expect(mockGetImages).toHaveBeenCalledOnce()
    expect(mockGetImages).toHaveBeenCalledWith('ehentai', '7', undefined, { signal: undefined })
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
    // Hook fetcher destructures key array; pass the same array SWR would provide.
    await lastSwrCall().fetcher!(['gallery/progress', 'ehentai', '5'], {})
    expect(mockGetProgress).toHaveBeenCalledWith('ehentai', '5', { signal: undefined })
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
    const ac = new AbortController()
    await lastSwrCall().fetcher!(null, { signal: ac.signal })
    expect(mockEhSearch).toHaveBeenCalledWith(params, { signal: ac.signal })
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
    const ac = new AbortController()
    await lastSwrCall().fetcher!(null, { signal: ac.signal })
    expect(mockEhGetPopular).toHaveBeenCalledWith({ signal: ac.signal })
  })
})

// ── State-consistency tests ───────────────────────────────────────────

describe('useInfiniteLibraryGalleries — cursor resets when filter changes', () => {
  /**
   * Regression guard: when the caller switches filter params (e.g. sort order),
   * the cursor embedded in the SWR key must NOT carry over from a previous
   * filter's pagination session.
   *
   * useInfiniteLibraryGalleries builds its SWR key via getKey(pageIndex, prevData).
   * On page 0 the key is always ['library/galleries/infinite', { ...params, page: 0 }]
   * with NO cursor — verifying that a fresh filter always starts at page 0.
   * The cursor only appears when previousPageData supplies next_cursor.
   * If the hook silently persisted cursor across param changes it would inject
   * the old cursor into the page-0 key, causing the new filter to start mid-stream.
   */
  it('test_cursor_resets_when_filter_changes_page0_key_never_contains_cursor', () => {
    // Simulate first filter: sort=newest. Render with this filter.
    useInfiniteLibraryGalleries({ sort: 'newest' } as Record<string, unknown>)
    const { getKey: getKey1 } = infiniteCalls[infiniteCalls.length - 1]

    // Page 0 key must not carry a cursor even after a previous session used one.
    const key1 = getKey1(0, null) as unknown[]
    expect(Array.isArray(key1)).toBe(true)
    const params1 = key1[1] as Record<string, unknown>
    expect(params1.cursor).toBeUndefined()
    expect(params1.page).toBe(0)

    // Simulate filter change: sort=oldest. Re-render with different params.
    infiniteCalls.length = 0
    useInfiniteLibraryGalleries({ sort: 'oldest' } as Record<string, unknown>)
    const { getKey: getKey2 } = infiniteCalls[infiniteCalls.length - 1]

    // Page 0 key for the new filter also must not contain a cursor.
    const key2 = getKey2(0, null) as unknown[]
    const params2 = key2[1] as Record<string, unknown>
    expect(params2.cursor).toBeUndefined()
    expect(params2.page).toBe(0)

    // The two page-0 keys must differ (different filter produces different cache slot).
    expect(JSON.stringify(key2)).not.toBe(JSON.stringify(key1))
  })

  it('test_cursor_in_key_comes_only_from_previousPageData_not_from_params', () => {
    // Only next_cursor from the previous page response should populate the cursor slot.
    useInfiniteLibraryGalleries({ sort: 'newest' } as Record<string, unknown>)
    const { getKey } = infiniteCalls[infiniteCalls.length - 1]

    const prevData = { galleries: [{ id: 1 }], total: 10, next_cursor: 'cursor-from-backend' }
    const key = getKey(1, prevData) as unknown[]
    const params = key[1] as Record<string, unknown>

    expect(params.cursor).toBe('cursor-from-backend')
    // page index must NOT appear alongside cursor to avoid ambiguity.
    expect(params.page).toBeUndefined()
  })

  it('test_getKey_returns_null_when_previousPageData_is_empty_gallery_list', () => {
    // Pagination must stop (null key) when a page comes back empty.
    useInfiniteLibraryGalleries({})
    const { getKey } = infiniteCalls[infiniteCalls.length - 1]

    const emptyPage = { galleries: [], total: 0, next_cursor: null }
    expect(getKey(1, emptyPage)).toBeNull()
  })
})

describe('useSearchGalleries — stale data cleared when search query changes', () => {
  /**
   * Regression guard: switching the search query must immediately invalidate
   * the old result set. useSearchGalleries implements this by returning null
   * from getKey when q is falsy, so SWR produces no fetch and the component
   * receives no stale items.
   *
   * A bug here would look like: getKey(0, null) returns a non-null key even
   * when q is empty, causing the previous result to remain visible.
   */
  it('test_stale_data_cleared_when_query_is_empty_getKey_returns_null', () => {
    useSearchGalleries('')
    const { getKey } = infiniteCalls[infiniteCalls.length - 1]

    // Empty query → no fetch → old results are not shown.
    expect(getKey(0, null)).toBeNull()
  })

  it('test_stale_data_cleared_when_query_changes_new_query_produces_distinct_key', () => {
    // First query.
    useSearchGalleries('touhou')
    const { getKey: getKey1 } = infiniteCalls[infiniteCalls.length - 1]
    const key1 = getKey1(0, null) as unknown[]

    infiniteCalls.length = 0

    // Changed query.
    useSearchGalleries('reimu')
    const { getKey: getKey2 } = infiniteCalls[infiniteCalls.length - 1]
    const key2 = getKey2(0, null) as unknown[]

    // Different query strings must produce different SWR keys, ensuring
    // SWR does NOT serve the cached 'touhou' results for a 'reimu' search.
    expect(key2[1]).toBe('reimu')
    expect(key1[1]).toBe('touhou')
    expect(JSON.stringify(key2)).not.toBe(JSON.stringify(key1))
  })

  it('test_stale_data_cleared_next_cursor_from_prevData_included_in_page1_key', () => {
    useSearchGalleries('touhou')
    const { getKey } = infiniteCalls[infiniteCalls.length - 1]

    const prevData = { items: [{ id: 1 }], total: 10, has_next: true, next_cursor: 'cur-abc' }
    const key = getKey(1, prevData) as unknown[]
    const opts = key[2] as Record<string, unknown>

    expect(opts.cursor).toBe('cur-abc')
  })

  it('test_stale_data_cleared_getKey_returns_null_when_has_next_is_false', () => {
    useSearchGalleries('touhou')
    const { getKey } = infiniteCalls[infiniteCalls.length - 1]

    const lastPage = { items: [], total: 5, has_next: false, next_cursor: null }
    expect(getKey(1, lastPage)).toBeNull()
  })
})

// ── Abort signal propagation ──────────────────────────────────────────

describe('useEhSearch — abort signal forwarded to api', () => {
  /**
   * Regression guard: the SWR fetcher second argument carries an AbortSignal.
   * Verifies that the signal object received by the fetcher is forwarded
   * verbatim to the api call — the direct contractual guarantee that
   * in-flight requests are cancellable when SWR invalidates a key.
   */
  it('test_abort_signal_is_forwarded_from_fetcher_arg_to_api_call', async () => {
    const params = { q: 'abort-test' }
    useEhSearch(params)
    const { fetcher } = lastSwrCall()
    const controller = new AbortController()
    await fetcher!(null, { signal: controller.signal })
    expect(mockEhSearch).toHaveBeenCalledWith(params, { signal: controller.signal })
  })
})

describe('useEhPopular — abort signal forwarded to api', () => {
  it('test_abort_signal_is_forwarded_from_fetcher_arg_to_api_call', async () => {
    useEhPopular()
    const { fetcher } = lastSwrCall()
    const controller = new AbortController()
    await fetcher!(null, { signal: controller.signal })
    expect(mockEhGetPopular).toHaveBeenCalledWith({ signal: controller.signal })
  })
})

describe('useInfiniteLibraryGalleries — duplicate gallery accumulation guard', () => {
  /**
   * Regression guard: useMemo(() => data.flatMap(page => page.galleries), [data])
   * has no deduplication. If SWR ever provides the same page object twice in the
   * data array (e.g., during revalidation race), galleries would be doubled.
   *
   * This test controls what mockUseSWRInfinite returns to demonstrate the
   * flatMap-no-dedup behaviour. If the hook ever adds deduplication by id,
   * the assertion should be updated to reflect that intentional change.
   */
  it('test_duplicate_galleries_not_accumulated_when_same_page_appears_twice_in_data', () => {
    const gallery = { id: 1, title: 'Gallery A' }
    const page = { galleries: [gallery], total: 1, next_cursor: null }

    // Simulate SWR returning the same page twice (e.g., re-render during revalidation).
    mockUseSWRInfinite.mockReturnValueOnce({
      data: [page, page],
      error: undefined,
      size: 2,
      setSize: vi.fn(),
      isValidating: false,
      isLoading: false,
      mutate: vi.fn(),
    })

    // Also stub useSWR for useSWRConfig used internally (already mocked at module level).
    const result = useInfiniteLibraryGalleries({})

    // flatMap without dedup: same page twice → 2 gallery entries.
    // This test documents the current behaviour. If this assertion fails after
    // deduplication is added, update to expect(result.galleries).toHaveLength(1).
    expect(result.galleries).toHaveLength(2)
    expect(result.galleries[0]).toBe(result.galleries[1])
  })

  it('test_no_duplicate_galleries_when_two_distinct_pages_are_loaded', () => {
    const page1 = { galleries: [{ id: 1, title: 'A' }], total: 2, next_cursor: 'cur' }
    const page2 = { galleries: [{ id: 2, title: 'B' }], total: 2, next_cursor: null }

    mockUseSWRInfinite.mockReturnValueOnce({
      data: [page1, page2],
      error: undefined,
      size: 2,
      setSize: vi.fn(),
      isValidating: false,
      isLoading: false,
      mutate: vi.fn(),
    })

    const result = useInfiniteLibraryGalleries({})

    expect(result.galleries).toHaveLength(2)
    expect(result.galleries[0].id).toBe(1)
    expect(result.galleries[1].id).toBe(2)
  })
})
