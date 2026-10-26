/**
 * The tab-restore flag is written from `useSearchParams().toString()` (spaces
 * as `+`, `:` as `%3A`), but `smartBack` compares it with the raw
 * `window.location`. These drive the real round trip — the tracker records the
 * page, a nav tab restores it, Next navigates to that recorded string — to
 * check that the two spellings never diverge for awkward queries and paths.
 * They do not: the restore navigates to the recorded (already canonical)
 * string, and parsing it as a URL leaves its encoding alone.
 *
 * The comparison itself is spelling-sensitive. A deep page that re-wrote its
 * own URL after arrival in another spelling (`%20`, a raw `:`) would stop the
 * climb; none does today (the Pixiv user page only writes `?tab=bookmarks`).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getTabHref, markTabRestore, rememberLocation } from '@/lib/navMemory'
import { smartBack } from '@/lib/navBack'

const ROOTS = ['/library', '/pixiv']

function makeRouter() {
  return { back: vi.fn(), push: vi.fn(), replace: vi.fn() }
}

/** Put the browser at `href` the way the App Router does for a client navigation. */
function navigateTo(href: string) {
  const url = new URL(href, window.location.href)
  window.history.replaceState({}, '', url.pathname + url.search)
}

/** What NavMemoryTracker records for the current location. */
function trackCurrentLocation() {
  const url = new URL(window.location.href)
  rememberLocation(ROOTS, url.pathname, url.searchParams.toString())
}

beforeEach(() => {
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
})

describe('smartBack after a nav-tab restore of a deep page', () => {
  it.each([
    ['a space typed as %20', '/pixiv/user/7?tab=bookmarks&q=long%20hair'],
    ['a space typed as +', '/pixiv/user/7?q=long+hair'],
    ['a raw colon', '/pixiv/user/7?q=artist:someone'],
    ['a literal plus', '/pixiv/user/7?q=a%2Bb'],
    ['unicode', '/pixiv/user/7?q=日本語'],
    ['an encoded ampersand and quote', "/pixiv/user/7?q=a%26b'c"],
    ['tilde and asterisk', '/pixiv/user/7?q=~a*b'],
    ['a path with spaces and unicode', '/library/local/My Gallery 日本'],
  ])('climbs to the section list for %s', (_name, firstArrival) => {
    // The list the user came from, then the deep page as they first reached it.
    navigateTo('/pixiv?tab=bookmarks')
    trackCurrentLocation()
    navigateTo('/library?q=x')
    trackCurrentLocation()
    navigateTo(firstArrival)
    trackCurrentLocation()
    const root = firstArrival.startsWith('/library') ? '/library' : '/pixiv'

    // Detour to the other section, then tap the tab: it flags and opens the
    // recorded deep URL.
    navigateTo(root === '/pixiv' ? '/library' : '/pixiv')
    const target = getTabHref(root)
    markTabRestore(target)
    navigateTo(target)

    const router = makeRouter()
    smartBack(router, root)

    expect(router.back).not.toHaveBeenCalled()
    expect(router.replace).toHaveBeenCalledWith(root === '/pixiv' ? '/pixiv?tab=bookmarks' : '/library?q=x')
  })
})
