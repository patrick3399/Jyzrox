import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

const replace = vi.fn()
let searchStr = ''
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(async () => ({
        galleries: [{ gid: 1, token: 'a' }],
        total: 2,
        page: 0,
        next_gid: 5,
      })),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [],
      })),
      getPopular: vi.fn(async () => ({ galleries: [{ gid: 9, token: 'p' }], total: 1, page: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
    },
  },
}))

import { useEhBrowse } from '@/hooks/useEhBrowse'
import { api } from '@/lib/api'
import {
  serializeSnapshot,
  reducer as rootReducer,
  initialState as base,
} from '@/lib/ehBrowseState'

beforeEach(() => {
  searchStr = ''
  replace.mockClear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('useEhBrowse — init', () => {
  it('derives initial tab from URL', () => {
    searchStr = 'tab=favorites&favcat=3'
    const { result } = renderHook(() => useEhBrowse())
    expect(result.current.state.tab).toBe('favorites')
    expect(result.current.state.filters.favCat).toBe('3')
  })
  it('commitQuery switches to search identity and resets view', () => {
    const { result } = renderHook(() => useEhBrowse())
    act(() => result.current.actions.commitQuery('foo'))
    expect(result.current.state.query).toBe('foo')
    expect(result.current.state.tab).toBe('search')
    expect(result.current.state.items).toHaveLength(0)
  })
})

describe('useEhBrowse — loadMore', () => {
  it('seeds the first page then appends the next', async () => {
    ;(api.eh.search as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ galleries: [{ gid: 1, token: 'a' }], total: 9, page: 0, next_gid: 5 })
      .mockResolvedValueOnce({ galleries: [{ gid: 2, token: 'b' }], total: 9, page: 1, next_gid: 8 })
    const { result } = renderHook(() => useEhBrowse())
    act(() => result.current.actions.commitQuery('foo'))
    await act(async () => {
      await result.current.loadMore()
    }) // seed
    expect(result.current.state.items.map((g) => g.gid)).toEqual([1])
    expect(result.current.state.cursor).toEqual({ kind: 'gid', nextGid: 5 })
    await act(async () => {
      await result.current.loadMore()
    }) // append
    expect(result.current.state.items.map((g) => g.gid)).toEqual([1, 2])
  })

  it('does not append a stale result after identity changed mid-flight', async () => {
    let resolveFirst: (v: unknown) => void = () => {}
    ;(api.eh.search as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((res) => (resolveFirst = res)),
    )
    const { result } = renderHook(() => useEhBrowse())
    act(() => result.current.actions.commitQuery('foo'))
    let p: Promise<void>
    act(() => {
      p = result.current.loadMore()
    })
    // identity changes before the first fetch resolves
    act(() => result.current.actions.commitQuery('bar'))
    await act(async () => {
      resolveFirst({ galleries: [{ gid: 99, token: 'z' }], total: 1, page: 0, next_gid: null })
      await p
    })
    expect(result.current.state.items.find((g) => g.gid === 99)).toBeUndefined()
  })
})

describe('useEhBrowse — loadMore does not wedge on all-duplicate pages', () => {
  const g = (gid: number) => ({ gid, token: `t${gid}` })
  it('keeps hasMore and advances the cursor when a page is fully duplicate but the cursor moved', async () => {
    searchStr = 'tab=favorites'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockReset()
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>)
      // seed
      .mockResolvedValueOnce({
        galleries: [g(1), g(2)],
        total: 10,
        has_next: true,
        next_cursor: 'A',
        categories: [],
      })
      // append #1: entirely duplicate gids, but cursor advances A→B
      .mockResolvedValueOnce({
        galleries: [g(1), g(2)],
        total: 10,
        has_next: true,
        next_cursor: 'B',
        categories: [],
      })
      // append #2: fresh items
      .mockResolvedValueOnce({
        galleries: [g(3), g(4)],
        total: 10,
        has_next: true,
        next_cursor: 'C',
        categories: [],
      })
    const { result } = renderHook(() => useEhBrowse())
    await act(async () => {
      await result.current.loadMore()
    }) // seed → [1,2]
    expect(result.current.state.items.map((x) => x.gid)).toEqual([1, 2])
    await act(async () => {
      await result.current.loadMore()
    }) // all-duplicate page: nothing appended, but the walk must not dead-end
    expect(result.current.state.items.map((x) => x.gid)).toEqual([1, 2])
    expect(result.current.state.hasMore).toBe(true)
    expect(result.current.state.cursor).toEqual({ kind: 'fav', next: 'B' })
    await act(async () => {
      await result.current.loadMore()
    }) // grid re-fires (gate reopens on zero-growth cycles) → fresh items land
    expect(result.current.state.items.map((x) => x.gid)).toEqual([1, 2, 3, 4])
    expect(result.current.state.cursor).toEqual({ kind: 'fav', next: 'C' })
  })

  it('stops (hasMore=false) when a page is all-duplicate and the cursor cannot advance', async () => {
    searchStr = 'tab=favorites'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockReset()
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        galleries: [g(1), g(2)],
        total: 2,
        has_next: true,
        next_cursor: 'A',
        categories: [],
      })
      // append: duplicates AND cursor does not advance (still 'A') → dead end
      .mockResolvedValue({
        galleries: [g(1), g(2)],
        total: 2,
        has_next: true,
        next_cursor: 'A',
        categories: [],
      })
    const { result } = renderHook(() => useEhBrowse())
    await act(async () => {
      await result.current.loadMore()
    })
    await act(async () => {
      await result.current.loadMore()
    })
    expect(result.current.state.items.map((x) => x.gid)).toEqual([1, 2])
    expect(result.current.state.hasMore).toBe(false)
  })
})

describe('useEhBrowse — in-page identity switch restores the previous view', () => {
  const g = (gid: number) => ({ gid, token: `t${gid}` })
  it('switching tab away and back restores buffer, cursor and scrollY without refetching', async () => {
    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(1), g(2)],
      total: 2,
      has_next: true,
      next_cursor: 'A',
      categories: [],
    })
    const { result } = renderHook(() => useEhBrowse())
    await act(async () => {
      await result.current.loadMore()
    }) // seed favorites → [1,2]
    expect(result.current.state.items.map((x) => x.gid)).toEqual([1, 2])

    // User is deep in the list when they switch to another tab.
    Object.defineProperty(window, 'scrollY', { value: 5000, configurable: true, writable: true })
    act(() => result.current.actions.setTab('popular'))
    expect(result.current.state.items).toHaveLength(0) // popular starts fresh
    await act(async () => {
      await result.current.loadMore()
    }) // seed popular

    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true, writable: true })
    act(() => result.current.actions.setTab('favorites'))

    // Favorites view must come back from the snapshot, not reseed from page 1.
    expect(result.current.state.items.map((x) => x.gid)).toEqual([1, 2])
    expect(result.current.state.cursor).toEqual({ kind: 'fav', next: 'A' })
    expect(result.current.state.hasMore).toBe(true)
    expect(result.current.state.scrollY).toBe(5000)
    expect(api.eh.getFavorites).toHaveBeenCalledTimes(1)
  })

  it('commitQuery from another tab restores a previously banked search view', async () => {
    searchStr = 'tab=search&q=foo'
    ;(api.eh.search as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [{ gid: 7, token: 'x' }],
      total: 1,
      page: 0,
      next_gid: 9,
    })
    const { result } = renderHook(() => useEhBrowse())
    await act(async () => {
      await result.current.loadMore()
    }) // seed search "foo" → [7]

    Object.defineProperty(window, 'scrollY', { value: 1234, configurable: true, writable: true })
    act(() => result.current.actions.setTab('popular'))
    act(() => result.current.actions.commitQuery('foo'))

    // Same search identity as before → restored, not refetched.
    expect(result.current.state.items.map((x) => x.gid)).toEqual([7])
    expect(result.current.state.scrollY).toBe(1234)
    expect(api.eh.search).toHaveBeenCalledTimes(1)
  })
})

describe('useEhBrowse — total normalization', () => {
  it('stores null rather than undefined when a source payload omits total', async () => {
    // Regression: /api/eh/popular shipped only { galleries }, so `total:
    // response.total` put undefined into a state field typed number | null.
    // Consumers guarding with `!== null` then dereferenced undefined.
    ;(api.eh.getPopular as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      galleries: [{ gid: 9, token: 'p' }],
    })
    const { result } = renderHook(() => useEhBrowse())
    await act(async () => {
      await result.current.loadMore()
    })
    expect(result.current.state.items.map((g) => g.gid)).toEqual([9])
    expect(result.current.state.total).toBeNull()
  })
})

describe('useEhBrowse — URL sync', () => {
  it('writes identity to the URL but never the view buffer', async () => {
    const replaceState = vi.spyOn(window.history, 'replaceState')
    ;(api.eh.search as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [{ gid: 1, token: 'a' }],
      total: 1,
      page: 0,
      next_gid: 5,
    })
    const { result } = renderHook(() => useEhBrowse())
    act(() => result.current.actions.commitQuery('kittens'))
    await act(async () => {
      await result.current.loadMore()
    })
    const lastUrl = String(replaceState.mock.calls.at(-1)?.[2])
    expect(lastUrl).toContain('q=kittens')
    expect(lastUrl).not.toMatch(/gid|scroll|next_gid/i)
    expect(replace).not.toHaveBeenCalled()
    replaceState.mockRestore()
  })
})

describe('useEhBrowse — snapshot restore', () => {
  it('restores buffer + scrollY on mount when queryKey matches the URL', () => {
    searchStr = 'tab=search&q=foo'
    let s = rootReducer(base, { type: 'SET_TAB', tab: 'search' })
    s = rootReducer(s, { type: 'COMMIT_QUERY', query: 'foo' })
    s = rootReducer(s, {
      type: 'SEED',
      items: [
        { gid: 1, token: 'a' },
        { gid: 2, token: 'b' },
      ] as never,
      total: 2,
      cursor: { kind: 'gid', nextGid: 7 },
      hasMore: true,
    })
    s = rootReducer(s, { type: 'SET_SCROLL', scrollY: 480 })
    sessionStorage.setItem('eh_browse_snapshot', serializeSnapshot(s))

    const { result } = renderHook(() => useEhBrowse())
    expect(result.current.state.items.map((g) => g.gid)).toEqual([1, 2])
    expect(result.current.state.scrollY).toBe(480)
    expect(result.current.state.cursor).toEqual({ kind: 'gid', nextGid: 7 })
  })

  it('resets to the home tab when the URL is cleared while mounted', () => {
    searchStr = 'tab=favorites&favcat=3'
    const { result, rerender } = renderHook(() => useEhBrowse())
    expect(result.current.state.tab).toBe('favorites')
    // External navigation to bare /e-hentai (e.g. nav double-tap) clears the query string.
    searchStr = ''
    rerender()
    expect(result.current.state.tab).toBe('popular')
    expect(result.current.state.filters.favCat).toBe('all')
  })

  it('ignores a snapshot whose queryKey does not match the URL', () => {
    searchStr = 'tab=search&q=different'
    let s = rootReducer(base, { type: 'SET_TAB', tab: 'search' })
    s = rootReducer(s, { type: 'COMMIT_QUERY', query: 'foo' })
    s = rootReducer(s, {
      type: 'SEED',
      items: [{ gid: 1, token: 'a' }] as never,
      total: 1,
      cursor: null,
      hasMore: false,
    })
    sessionStorage.setItem('eh_browse_snapshot', serializeSnapshot(s))
    const { result } = renderHook(() => useEhBrowse())
    expect(result.current.state.items).toHaveLength(0)
  })
})
