/**
 * E-Hentai scroll/buffer restore regression coverage.
 *
 * 1. Cross-page round-trip: navigating away (unmount) and back with the same
 *    URL identity must restore the buffer without refetching and re-apply the
 *    banked window scroll.
 * 2. In-page tab round-trip: switching to another tab and back (no remount!)
 *    must do the same via the per-identity snapshot store — this regressed in
 *    the single-slot snapshot model where any identity switch wiped the view.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { useLayoutEffect } from 'react'

let searchStr = ''
const push = vi.fn()
const gridRestoreApplied = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))
vi.mock('@/components/VirtualGrid', async () => {
  const { useEffect } = await import('react')
  return {
    VirtualGrid: ({
      items,
      onRegisterElement,
      onRestoreApplied,
      restoreRequest,
      renderItem,
    }: {
      items: Array<{ gid: number }>
      onRegisterElement?: (index: number, element: HTMLElement | null) => void
      onRestoreApplied?: (request: { key: string; index: number }) => void
      restoreRequest?: { key: string; index: number }
      renderItem: (item: { gid: number }, index: number) => React.ReactNode
    }) => {
      useEffect(() => {
        if (restoreRequest) {
          gridRestoreApplied(restoreRequest)
          onRestoreApplied?.(restoreRequest)
        }
      }, [onRestoreApplied, restoreRequest])
      return (
        <div>
          {items.map((item, index) => (
            <div
              key={item.gid}
              ref={(element) => onRegisterElement?.(index, element)}
            >
              {renderItem(item, index)}
            </div>
          ))}
        </div>
      )
    },
  }
})
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(),
      getFavorites: vi.fn(),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
    },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
  },
}))

import Page from '@/app/e-hentai/page'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { snapshotStorageKey } from '@/lib/browse/snapshotStore'

const g = (gid: number, title: string) =>
  ({
    gid,
    token: `t${gid}`,
    title,
    title_jpn: '',
    category: 'manga',
    thumb: '',
    uploader: 'u',
    posted_at: 0,
    pages: 1,
    rating: 0,
    tags: [],
    expunged: false,
  }) as never

function setScrollY(value: number) {
  Object.defineProperty(window, 'scrollY', { value, configurable: true, writable: true })
}

async function flushRaf() {
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
}

beforeEach(() => {
  searchStr = ''
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'list') // deterministic rendering (no virtualization)
  vi.clearAllMocks()
  setScrollY(0)
})

describe('e-hentai favorites snapshot round-trip', () => {
  it('restores buffer and scroll position after unmount/remount with same URL', async () => {
    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(1, 'Alpha'), g(2, 'Beta')],
      total: 2,
      has_next: true,
      next_cursor: 'A',
      categories: [],
    })

    const first = render(<Page />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    expect(api.eh.getFavorites).toHaveBeenCalledTimes(1)

    // User has scrolled deep (real scrolling emits scroll events); unmount
    // (bottom-tab navigation away) banks the position.
    setScrollY(5000)
    fireEvent.scroll(window)
    await flushRaf()
    first.unmount()

    // Return with the SAME url (navMemory remembers /e-hentai?tab=favorites&favcat=3)
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    setScrollY(0)

    render(<Page />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    // Buffer restored, not refetched:
    expect(api.eh.getFavorites).toHaveBeenCalledTimes(1)

    await flushRaf()
    expect(scrollTo).toHaveBeenCalledWith(0, 5000)
    vi.unstubAllGlobals()
  })

  it('unmount write must not capture the router scroll reset as the banked position', async () => {
    // Next.js resets window scroll to 0 in the NEW page's layout phase, and
    // React runs the old page's passive unmount cleanup AFTER that — so the
    // exit write must use the last user scroll position, not live scrollY.
    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(1, 'Alpha'), g(2, 'Beta')],
      total: 2,
      has_next: true,
      next_cursor: 'A',
      categories: [],
    })

    const first = render(<Page />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())

    // User scrolls deep; the continuous capture sees a real scroll event.
    setScrollY(5000)
    fireEvent.scroll(window)
    await flushRaf()

    // Router push away: Next scrolls to top BEFORE the unmount cleanup runs.
    // (The reset's scroll event is delivered async, after the listener is gone.)
    setScrollY(0)
    first.unmount()

    // Return to the list URL (smartBack push) — banked position must survive.
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    await flushRaf()
    expect(scrollTo).toHaveBeenCalledWith(0, 5000)
    vi.unstubAllGlobals()
  })

  it('the incoming page’s scroll reset event cannot poison the banked position', async () => {
    // Next resets window scroll in the INCOMING page's layout phase and the
    // reset's scroll event fires before React's passive cleanups — so the
    // browse page's scroll listener must already be detached by then (layout
    // cleanup runs in the mutation phase, before sibling layout effects).
    function RouterScrollReset() {
      useLayoutEffect(() => {
        setScrollY(0)
        window.dispatchEvent(new Event('scroll'))
      }, [])
      return null
    }
    const Shell = ({ browse }: { browse: boolean }) => (browse ? <Page /> : <RouterScrollReset />)

    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(1, 'Alpha'), g(2, 'Beta')],
      total: 2,
      has_next: true,
      next_cursor: 'A',
      categories: [],
    })

    const view = render(<Shell browse />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    setScrollY(5000)
    fireEvent.scroll(window)
    await flushRaf()

    // Navigate away: browse page unmounts in the same commit that mounts the
    // "incoming page", whose layout effect resets scroll and emits the event.
    view.rerender(<Shell browse={false} />)

    const tabId = sessionStorage.getItem('browse_session_tab_id_v1')
    expect(tabId).not.toBeNull()
    const scopedKey = snapshotStorageKey({
      userId: 'qa-user',
      tabId: tabId!,
      sourceId: 'ehentai',
      schemaVersion: 1,
    })
    const store = JSON.parse(sessionStorage.getItem(scopedKey)!) as {
      entries: Array<{
        identityKey: string
        snapshot: { anchor: { scrollY: number } | null }
      }>
    }
    const favoriteEntry = store.entries.find((entry) =>
      entry.identityKey.includes('"surface":"favorites"'),
    )
    expect(favoriteEntry?.snapshot.anchor?.scrollY).toBe(5000)
  })

  it('restores buffer and scroll position after an in-page tab switch away and back', async () => {
    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(1, 'Alpha'), g(2, 'Beta')],
      total: 2,
      has_next: true,
      next_cursor: 'A',
      categories: [],
    })

    render(<Page />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    expect(api.eh.getFavorites).toHaveBeenCalledTimes(1)

    // Deep in the favorites list, switch to the popular tab in-page…
    setScrollY(5000)
    fireEvent.click(screen.getAllByText(t('browse.popularTab'))[0])
    await waitFor(() => expect(api.eh.getPopular).toHaveBeenCalled())
    expect(screen.queryByText('Alpha')).not.toBeInTheDocument()

    // …then come back.
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    setScrollY(0)
    fireEvent.click(screen.getAllByText(t('browse.favoritesTab'))[0])

    // Favorites buffer restored from the per-identity snapshot, not reseeded.
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    expect(api.eh.getFavorites).toHaveBeenCalledTimes(1)

    // Banked scroll position re-applied even though the page never remounted.
    await flushRaf()
    expect(scrollTo).toHaveBeenCalledWith(0, 5000)
    vi.unstubAllGlobals()
  })

  it('keeps pointer-navigation pages under gid 314 and never writes its view into the next identity', async () => {
    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(314, 'Pointer 314')],
      total: 1,
      has_next: false,
      next_cursor: null,
      categories: [],
    })

    render(<Page />)
    await waitFor(() => expect(screen.getByText('Pointer 314')).toBeInTheDocument())
    setScrollY(3140)
    fireEvent.scroll(window)
    await flushRaf()
    fireEvent.click(screen.getByText('Pointer 314'))
    expect(push).toHaveBeenCalledWith('/e-hentai/314/t314?fav=1')

    fireEvent.click(screen.getAllByText(t('browse.popularTab'))[0])
    await waitFor(() => expect(api.eh.getPopular).toHaveBeenCalled())

    const tabId = sessionStorage.getItem('browse_session_tab_id_v1')
    expect(tabId).not.toBeNull()
    const scopedKey = snapshotStorageKey({
      userId: 'qa-user',
      tabId: tabId!,
      sourceId: 'ehentai',
      schemaVersion: 1,
    })
    const store = JSON.parse(sessionStorage.getItem(scopedKey)!) as {
      entries: Array<{
        identityKey: string
        snapshot: {
          pages: Array<Array<{ gid: number }>>
          anchor: { itemId: number | null } | null
        }
      }>
    }
    const favorite = store.entries.find((entry) =>
      entry.identityKey.includes('"surface":"favorites"'),
    )
    const popular = store.entries.find((entry) =>
      entry.identityKey.includes('"surface":"popular"'),
    )
    expect(favorite?.snapshot.pages.flat().map((item) => item.gid)).toContain(314)
    expect(popular?.snapshot.anchor?.itemId ?? null).not.toBe(314)
  })

  it('re-applies an already-restored list anchor after another same-mount round-trip', async () => {
    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(1, 'Alpha'), g(2, 'Beta')],
      total: 2,
      has_next: true,
      next_cursor: 'A',
      categories: [],
    })

    render(<Page />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    await flushRaf()
    scrollTo.mockClear()

    setScrollY(5000)
    fireEvent.click(screen.getAllByText(t('browse.popularTab'))[0])
    await waitFor(() => expect(screen.queryByText('Alpha')).not.toBeInTheDocument())
    await flushRaf()
    expect(scrollTo).toHaveBeenCalledOnce()
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    scrollTo.mockClear()
    setScrollY(0)
    fireEvent.click(screen.getAllByText(t('browse.favoritesTab'))[0])
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    await flushRaf()
    expect(scrollTo).toHaveBeenCalledWith(0, 5000)

    scrollTo.mockClear()
    setScrollY(7000)
    fireEvent.scroll(window)
    await flushRaf()
    fireEvent.click(screen.getAllByText(t('browse.popularTab'))[0])
    await waitFor(() => expect(screen.queryByText('Alpha')).not.toBeInTheDocument())
    await flushRaf()
    expect(scrollTo).toHaveBeenCalledOnce()
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    scrollTo.mockClear()
    setScrollY(0)
    fireEvent.click(screen.getAllByText(t('browse.favoritesTab'))[0])
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    await flushRaf()

    expect(scrollTo).toHaveBeenCalledWith(0, 7000)
    vi.unstubAllGlobals()
  })

  it('re-applies an already-restored grid anchor after another same-mount round-trip', async () => {
    localStorage.setItem('eh_view_mode', 'grid')
    searchStr = 'tab=favorites&favcat=3'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(1, 'Alpha'), g(2, 'Beta')],
      total: 2,
      has_next: true,
      next_cursor: 'A',
      categories: [],
    })

    render(<Page />)
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    await flushRaf()
    scrollTo.mockClear()

    setScrollY(5000)
    fireEvent.scroll(window)
    await flushRaf()
    expect(scrollTo).not.toHaveBeenCalled()
    fireEvent.click(screen.getAllByText(t('browse.popularTab'))[0])
    await waitFor(() => expect(screen.queryByText('Alpha')).not.toBeInTheDocument())
    await flushRaf()
    expect(scrollTo).toHaveBeenCalledOnce()
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    scrollTo.mockClear()
    setScrollY(0)
    fireEvent.click(screen.getAllByText(t('browse.favoritesTab'))[0])
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    await flushRaf()
    expect(gridRestoreApplied).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledOnce()
    expect(gridRestoreApplied.mock.invocationCallOrder[0]).toBeLessThan(
      scrollTo.mock.invocationCallOrder[0],
    )
    const firstRestoreKey = gridRestoreApplied.mock.calls[0]?.[0]?.key

    scrollTo.mockClear()
    gridRestoreApplied.mockClear()
    setScrollY(7000)
    fireEvent.scroll(window)
    await flushRaf()
    fireEvent.click(screen.getAllByText(t('browse.popularTab'))[0])
    await waitFor(() => expect(screen.queryByText('Alpha')).not.toBeInTheDocument())
    await flushRaf()
    expect(scrollTo).toHaveBeenCalledOnce()
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    scrollTo.mockClear()
    expect(gridRestoreApplied).not.toHaveBeenCalled()
    setScrollY(0)
    fireEvent.click(screen.getAllByText(t('browse.favoritesTab'))[0])
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    await flushRaf()

    expect(gridRestoreApplied).toHaveBeenCalledTimes(1)
    expect(gridRestoreApplied.mock.calls[0]?.[0]?.key).not.toBe(firstRestoreKey)
    expect(scrollTo).toHaveBeenCalledOnce()
    vi.unstubAllGlobals()
  })
})
