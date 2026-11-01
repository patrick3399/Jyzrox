import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'

/**
 * Regression: the tab-restore flag (`nav_restore_flag_v1`) was only consumed by
 * smartBack. If the user left the restored page any other way — a link, browser
 * back, another tab — it stayed armed, so a later ordinary arrival at that same
 * URL made back climb to the section list (replace) instead of walking history.
 * The tracker sees every committed URL, so it disarms the flag once the user has
 * moved off the flagged page.
 */

const nav = vi.hoisted(() => ({ pathname: '/', search: '' }))

vi.mock('next/navigation', () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
}))

import { NavMemoryTracker } from '@/components/NavMemoryTracker'
import { consumeTabRestore, getTabHref, markTabRestore } from '@/lib/navMemory'
import { smartBack } from '@/lib/navBack'

const FLAGGED = '/e-hentai/123/abc?fav=1'

function go(pathname: string, search: string, rerender: () => void) {
  nav.pathname = pathname
  nav.search = search
  window.history.pushState({}, '', search ? `${pathname}?${search}` : pathname)
  rerender()
}

describe('NavMemoryTracker tab-restore flag', () => {
  let historyLength = 5

  beforeEach(() => {
    sessionStorage.clear()
    historyLength = 5
    Object.defineProperty(window.history, 'length', {
      configurable: true,
      get: () => historyLength,
    })
    nav.pathname = '/library'
    nav.search = ''
  })

  afterEach(() => {
    delete (window.history as unknown as { length?: number }).length
  })

  it('still records the location against its tab root', () => {
    nav.pathname = '/e-hentai/123/abc'
    nav.search = 'fav=1'
    render(<NavMemoryTracker />)
    expect(getTabHref('/e-hentai')).toBe(FLAGGED)
  })

  it('keeps the flag when the flagged destination commits', () => {
    markTabRestore(FLAGGED)
    const { rerender } = render(<NavMemoryTracker />)

    go('/e-hentai/123/abc', 'fav=1', () => rerender(<NavMemoryTracker />))

    expect(consumeTabRestore(FLAGGED)).toBe(true)
  })

  it('disarms the flag when the user leaves the restored page without going back', () => {
    const { rerender } = render(<NavMemoryTracker />)
    markTabRestore(FLAGGED)
    go('/e-hentai/123/abc', 'fav=1', () => rerender(<NavMemoryTracker />))

    // Leaves by an in-page link / another route, never touching smartBack.
    go('/e-hentai/456/def', '', () => rerender(<NavMemoryTracker />))

    expect(consumeTabRestore(FLAGGED)).toBe(false)
  })

  it('walks history, not the section list, when the same URL is reached again later', () => {
    const router = { back: vi.fn(), push: vi.fn(), replace: vi.fn() }
    const { rerender } = render(<NavMemoryTracker />)
    markTabRestore(FLAGGED)
    go('/e-hentai/123/abc', 'fav=1', () => rerender(<NavMemoryTracker />))
    go('/library', '', () => rerender(<NavMemoryTracker />))

    // An ordinary arrival at the formerly flagged URL.
    go('/e-hentai/123/abc', 'fav=1', () => rerender(<NavMemoryTracker />))
    smartBack(router, '/e-hentai')

    expect(router.replace).not.toHaveBeenCalled()
    expect(router.back).toHaveBeenCalledTimes(1)
  })

  it('does not drop a flag whose destination has not committed yet', () => {
    const { rerender } = render(<NavMemoryTracker />)
    markTabRestore(FLAGGED)

    // Something else commits first (e.g. the page being left rewrites its URL).
    go('/library', 'sort=name', () => rerender(<NavMemoryTracker />))
    go('/e-hentai/123/abc', 'fav=1', () => rerender(<NavMemoryTracker />))

    expect(consumeTabRestore(FLAGGED)).toBe(true)
  })

  it('leaves a newer flag for another page alone when the old restored page is left', () => {
    const { rerender } = render(<NavMemoryTracker />)
    markTabRestore(FLAGGED)
    go('/e-hentai/123/abc', 'fav=1', () => rerender(<NavMemoryTracker />))

    // Tapping another tab arms a flag for its destination, then that commits.
    markTabRestore('/pixiv/user/9')
    go('/pixiv/user/9', '', () => rerender(<NavMemoryTracker />))

    expect(consumeTabRestore('/pixiv/user/9')).toBe(true)
  })
})
