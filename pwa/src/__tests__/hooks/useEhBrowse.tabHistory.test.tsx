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
