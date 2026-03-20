/**
 * useImageBrowser — Vitest test suite
 *
 * Covers:
 *   useImageBrowser — calls useSWRInfinite with key function
 *   useImageBrowser — getKey returns ['library/images', params] for page 0
 *   useImageBrowser — getKey returns null when previousPageData has no has_next
 *   useImageBrowser — getKey uses next_cursor from previousPageData for subsequent pages
 *   useImageBrowser — configures revalidateOnFocus: false
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockBrowseImages } = vi.hoisted(() => ({
  mockBrowseImages: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      browseImages: mockBrowseImages,
    },
  },
}))

// ── React mock — stub useMemo to return a predictable value ────────────

vi.mock('react', async () => {
  const actual = await vi.importActual<typeof import('react')>('react')
  return {
    ...actual,
    useMemo: (fn: () => unknown) => fn(),
  }
})

// ── swr/infinite mock ──────────────────────────────────────────────────

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
        data: undefined,
        error: undefined,
        size: 1,
        setSize: vi.fn(),
        isValidating: false,
        isLoading: false,
      }
    },
  ),
}))

vi.mock('swr/infinite', () => ({
  default: mockUseSWRInfinite,
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useImageBrowser } from '@/hooks/useImageBrowser'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  infiniteCalls.length = 0
  mockBrowseImages.mockResolvedValue({ images: [], has_next: false, next_cursor: null })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastInfiniteCall(): InfiniteCall {
  return infiniteCalls[infiniteCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useImageBrowser', () => {
  it('test_useImageBrowser_callsUseSWRInfiniteOnce', () => {
    useImageBrowser()
    expect(mockUseSWRInfinite).toHaveBeenCalledOnce()
  })

  it('test_useImageBrowser_getKey_pageZero_returnsArrayKeyWithLibraryImages', () => {
    const params = { tags: ['tag1'], sort: 'newest' as const }
    useImageBrowser(params)
    const { getKey } = lastInfiniteCall()
    const key = getKey(0, null)
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('library/images')
    expect((key as unknown[])[1]).toEqual(params)
  })

  it('test_useImageBrowser_getKey_previousPageHasNoNext_returnsNull', () => {
    useImageBrowser()
    const { getKey } = lastInfiniteCall()
    const key = getKey(1, { images: [], has_next: false, next_cursor: null })
    expect(key).toBeNull()
  })

  it('test_useImageBrowser_getKey_previousPageHasNextCursor_includesCursorInKey', () => {
    const params = { gallery_id: 5 }
    useImageBrowser(params)
    const { getKey } = lastInfiniteCall()
    const key = getKey(1, { images: [], has_next: true, next_cursor: 'cursor-abc' })
    expect(Array.isArray(key)).toBe(true)
    const keyParams = (key as unknown[])[1] as Record<string, unknown>
    expect(keyParams.cursor).toBe('cursor-abc')
  })

  it('test_useImageBrowser_options_setsRevalidateOnFocusFalse', () => {
    useImageBrowser()
    expect(lastInfiniteCall().options.revalidateOnFocus).toBe(false)
  })

  it('test_useImageBrowser_returnsLoadMoreFunctionThatIncrementsSize', () => {
    const mockSetSize = vi.fn()
    mockUseSWRInfinite.mockReturnValueOnce({
      data: undefined,
      error: undefined,
      size: 2,
      setSize: mockSetSize,
      isValidating: false,
      isLoading: false,
    })
    const { loadMore, size } = useImageBrowser()
    loadMore()
    expect(mockSetSize).toHaveBeenCalledWith(size + 1)
  })

  it('includes jump_at in page 0 key when jumpAt is provided', () => {
    useImageBrowser({ tags: ['tag1'], jumpAt: '2024-06-01T00:00:00Z' })
    const { getKey } = lastInfiniteCall()
    const key = getKey(0, null) as [string, Record<string, unknown>]
    expect(key[1]).toHaveProperty('jump_at', '2024-06-01T00:00:00Z')
    // jumpAt should NOT appear as a raw property (it's renamed to jump_at)
    expect(key[1]).not.toHaveProperty('jumpAt')
  })

  it('excludes jump_at from subsequent page keys using cursor', () => {
    useImageBrowser({ tags: ['tag1'], jumpAt: '2024-06-01T00:00:00Z' })
    const { getKey } = lastInfiniteCall()
    const key = getKey(1, { images: [], has_next: true, next_cursor: 'cursor-xyz' }) as [
      string,
      Record<string, unknown>,
    ]
    expect(key[1]).not.toHaveProperty('jump_at')
    expect(key[1]).not.toHaveProperty('jumpAt')
    expect(key[1]).toHaveProperty('cursor', 'cursor-xyz')
  })
})
