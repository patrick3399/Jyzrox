import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// With commitBrowseUrl passing a fresh state object, the App Router's history
// patch dispatches ACTION_RESTORE, so useSearchParams follows the URL that was
// written. Model that by reading the live location instead of a fixed string.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}))
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(async () => ({ galleries: [], total: 0, page: 0, next_gid: null })),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [],
      })),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
    },
  },
}))

import { useEhBrowse } from '@/hooks/useEhBrowse'

/** Put the page on `url` without going through the code under test. */
function startAt(url: string) {
  window.history.replaceState({}, '', url)
}

describe('useEhBrowse — which identity changes are reachable by back', () => {
  let pushState: ReturnType<typeof vi.spyOn>
  let replaceState: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    sessionStorage.clear()
    vi.clearAllMocks()
    startAt('/e-hentai')
    pushState = vi.spyOn(window.history, 'pushState')
    replaceState = vi.spyOn(window.history, 'replaceState')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // Regression: every in-page identity change replaced the URL, so popular ->
  // favorites -> favcat 8 collapsed into a single history entry. The browse
  // list has no back FAB, so on mobile the only back affordance is the edge
  // swipe, and it left E-Hentai entirely instead of stepping back a tab.
  it('switching tab pushes so the previous tab stays reachable', () => {
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))

    act(() => result.current.actions.setTab('favorites'))

    expect(pushState).toHaveBeenCalledTimes(1)
    expect(pushState.mock.calls[0][2]).toBe('/e-hentai?tab=favorites')
  })

  it('changing a filter inside the same tab replaces, so the pills do not each bank an entry', () => {
    startAt('/e-hentai?tab=favorites')
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    pushState.mockClear()
    replaceState.mockClear()

    act(() => result.current.actions.setFilter({ favCat: '8' }))

    expect(pushState).not.toHaveBeenCalled()
    expect(replaceState).toHaveBeenCalledTimes(1)
    expect(replaceState.mock.calls[0][2]).toBe('/e-hentai?tab=favorites&favcat=8')
  })

  it('committing a query from a non-search tab pushes, because it changes tab', () => {
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))

    act(() => result.current.actions.commitQuery('kemono'))

    expect(pushState).toHaveBeenCalledTimes(1)
    expect(pushState.mock.calls[0][2]).toBe('/e-hentai?q=kemono')
  })

  it('re-committing a query while already on the search tab replaces', () => {
    startAt('/e-hentai?q=kemono')
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    pushState.mockClear()
    replaceState.mockClear()

    act(() => result.current.actions.commitQuery('another'))

    expect(pushState).not.toHaveBeenCalled()
    expect(replaceState).toHaveBeenCalledTimes(1)
  })

  // The push is only useful if the entry it banks is live: going back changes the
  // query string while the page stays mounted, so the identity must resync from
  // the URL rather than keep showing the tab the user just left.
  it('going back to the pushed entry resyncs the identity from the URL', async () => {
    const { result, rerender } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    await act(async () => {})
    expect(result.current.state.tab).toBe('popular')

    act(() => result.current.actions.setTab('favorites'))
    await act(async () => {})
    expect(result.current.state.tab).toBe('favorites')

    // What popstate produces: the URL is back on the previous entry, and the
    // page re-renders without unmounting.
    startAt('/e-hentai')
    await act(async () => {
      rerender()
    })

    expect(result.current.state.tab).toBe('popular')
  })

  // Latest and a query search share `tab: 'search'` but are different surfaces
  // (lib/browse/ehentai.ts). Comparing tabs made Popular -> Latest -> "foo"
  // replace the Latest entry, so back skipped Latest and landed on Popular.
  it('Latest -> query search pushes, because they are different surfaces on the same tab', () => {
    startAt('/e-hentai?tab=search')
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    pushState.mockClear()
    replaceState.mockClear()

    act(() => result.current.actions.commitQuery('foo'))

    expect(pushState).toHaveBeenCalledTimes(1)
    expect(pushState.mock.calls[0][2]).toBe('/e-hentai?q=foo')
    expect(replaceState).not.toHaveBeenCalled()
  })

  it('Popular -> Latest -> search banks one entry per surface, so back can retrace both', () => {
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))

    act(() => result.current.actions.setTab('search'))
    act(() => result.current.actions.commitQuery('foo'))

    expect(pushState).toHaveBeenCalledTimes(2)
    expect(pushState.mock.calls[0][2]).toBe('/e-hentai?tab=search')
    expect(pushState.mock.calls[1][2]).toBe('/e-hentai?q=foo')
  })

  it('refining a query search to another query still replaces', () => {
    startAt('/e-hentai?q=foo')
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    pushState.mockClear()
    replaceState.mockClear()

    act(() => result.current.actions.commitQuery('foo bar'))

    expect(pushState).not.toHaveBeenCalled()
    expect(replaceState).toHaveBeenCalledTimes(1)
  })

  it('changing a filter on the Latest surface replaces', () => {
    startAt('/e-hentai?tab=search')
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    pushState.mockClear()
    replaceState.mockClear()

    act(() => result.current.actions.setFilter({ selectedCats: ['manga'] }))

    expect(pushState).not.toHaveBeenCalled()
    expect(replaceState).toHaveBeenCalledTimes(1)
  })

  // Regression: Popular -> "foo" (push) -> Clear search forced a replace to
  // Popular, leaving history [popular, popular]; the first back did nothing.
  describe('clearing a search', () => {
    let back: ReturnType<typeof vi.spyOn>

    beforeEach(() => {
      // jsdom would fire popstate asynchronously; the hook's contract is only
      // that it asks the browser to step back.
      back = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    })

    it('steps back when this page pushed the search entry, instead of banking a duplicate', () => {
      const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
      act(() => result.current.actions.commitQuery('foo'))
      expect(pushState).toHaveBeenCalledTimes(1)
      pushState.mockClear()
      replaceState.mockClear()

      act(() => result.current.actions.clearSearch())

      expect(back).toHaveBeenCalledTimes(1)
      expect(pushState).not.toHaveBeenCalled()
      expect(replaceState).not.toHaveBeenCalled()
    })

    it('still steps back after the query was refined inside the pushed search entry', () => {
      const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
      act(() => result.current.actions.commitQuery('foo'))
      act(() => result.current.actions.commitQuery('foo bar'))
      pushState.mockClear()
      replaceState.mockClear()

      act(() => result.current.actions.clearSearch())

      expect(back).toHaveBeenCalledTimes(1)
      expect(replaceState).not.toHaveBeenCalled()
    })

    it('replaces when the search was not pushed by this page (deep link / reload)', () => {
      startAt('/e-hentai?q=foo')
      const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
      pushState.mockClear()
      replaceState.mockClear()

      act(() => result.current.actions.clearSearch())

      expect(back).not.toHaveBeenCalled()
      expect(pushState).not.toHaveBeenCalled()
      expect(replaceState).toHaveBeenCalledTimes(1)
      expect(replaceState.mock.calls[0][2]).toBe('/e-hentai?tab=popular')
    })

    it('replaces when the pushed entry is no longer current (history moved under the page)', async () => {
      const { result, rerender } = renderHook(() => useEhBrowse({ userId: 'u1' }))
      act(() => result.current.actions.commitQuery('foo'))
      // Browser back then a different deep link: the page now shows another
      // search it did not push.
      startAt('/e-hentai?q=other')
      await act(async () => {
        rerender()
      })
      pushState.mockClear()
      replaceState.mockClear()

      act(() => result.current.actions.clearSearch())

      expect(back).not.toHaveBeenCalled()
      expect(replaceState).toHaveBeenCalledTimes(1)
    })
  })

  // Regression: image search hard-coded 'replace', overwriting the previous
  // tab's entry, so back from image results left E-Hentai entirely.
  it('showing image-search results from Popular pushes so back returns to Popular', () => {
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    pushState.mockClear()
    replaceState.mockClear()

    act(() => result.current.actions.showExternalResults([], 0))

    expect(pushState).toHaveBeenCalledTimes(1)
    expect(String(pushState.mock.calls[0][2])).toMatch(/^\/e-hentai\?tab=search&image_session=/)
    expect(replaceState).not.toHaveBeenCalled()
  })

  it('a second image search replaces the first instead of stacking sessions', () => {
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    act(() => result.current.actions.showExternalResults([], 0))
    pushState.mockClear()
    replaceState.mockClear()

    act(() => result.current.actions.showExternalResults([], 0))

    expect(pushState).not.toHaveBeenCalled()
    expect(replaceState).toHaveBeenCalledTimes(1)
  })

  // Regression: `advancedOpen` is excluded from the identity key, so toggling the
  // panel hit commitIdentity's same-key early return and never wrote `adv_open`.
  // After reader -> back the panel was open or closed depending on click history.
  describe('advanced panel expansion', () => {
    it('writes adv_open (as a replace) when the panel is opened, although the identity key is unchanged', () => {
      startAt('/e-hentai?tab=search')
      const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
      pushState.mockClear()
      replaceState.mockClear()

      act(() => result.current.actions.setFilter({ advancedOpen: true }))

      expect(pushState).not.toHaveBeenCalled()
      expect(replaceState).toHaveBeenCalledTimes(1)
      expect(replaceState.mock.calls[0][2]).toBe('/e-hentai?tab=search&adv_open=1')
    })

    it('drops adv_open from the URL when the panel is closed again', () => {
      startAt('/e-hentai?tab=search&adv_open=1')
      const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
      expect(result.current.state.filters.advancedOpen).toBe(true)
      pushState.mockClear()
      replaceState.mockClear()

      act(() => result.current.actions.setFilter({ advancedOpen: false }))

      expect(replaceState).toHaveBeenCalledTimes(1)
      expect(replaceState.mock.calls[0][2]).toBe('/e-hentai?tab=search')
    })

    it('a remount reads the panel state back from the URL it wrote', () => {
      startAt('/e-hentai?tab=search')
      const first = renderHook(() => useEhBrowse({ userId: 'u1' }))
      act(() => first.result.current.actions.setFilter({ advancedOpen: true }))
      first.unmount()

      const second = renderHook(() => useEhBrowse({ userId: 'u1' }))

      expect(second.result.current.state.filters.advancedOpen).toBe(true)
    })

    it('does not touch the URL for a flag the current surface does not serialize', () => {
      const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
      pushState.mockClear()
      replaceState.mockClear()

      // Popular has no advanced panel, so adv_open is not part of its URL.
      act(() => result.current.actions.setFilter({ advancedOpen: true }))

      expect(pushState).not.toHaveBeenCalled()
      expect(replaceState).not.toHaveBeenCalled()
    })
  })

  it('an explicit history mode from the caller still wins over the derived one', () => {
    startAt('/e-hentai?tab=favorites')
    const { result } = renderHook(() => useEhBrowse({ userId: 'u1' }))
    pushState.mockClear()
    replaceState.mockClear()

    // Same tab, so the derived mode would be replace.
    act(() => result.current.actions.setFilter({ favCat: '8' }, 'push'))

    expect(pushState).toHaveBeenCalledTimes(1)
    expect(replaceState).not.toHaveBeenCalled()
  })
})
