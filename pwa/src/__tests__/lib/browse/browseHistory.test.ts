import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { commitBrowseUrl } from '@/lib/browse/browseHistory'

/** Faithful stand-in for the App Router's pushState/replaceState patch.
 *
 *  next/dist/client/components/app-router.js bails out to the unpatched call
 *  when the supplied state already carries `__NA` or `_N`, and only otherwise
 *  copies its internals forward and dispatches ACTION_RESTORE so usePathname
 *  and useSearchParams hold the new URL. Passing `window.history.state` back in
 *  therefore silently opts out of that sync.
 *
 *  jsdom has no App Router, so the tests install this model and assert the call
 *  we make satisfies the contract. */
function installNextHistoryPatch() {
  const originalPush = window.history.pushState.bind(window.history)
  const originalReplace = window.history.replaceState.bind(window.history)
  const syncedUrls: string[] = []

  function copyNextJsInternalHistoryState(data: Record<string, unknown> | null) {
    const next = data ?? {}
    const current = window.history.state
    if (current?.__NA) next.__NA = current.__NA
    if (current?.__PRIVATE_NEXTJS_INTERNALS_TREE) {
      next.__PRIVATE_NEXTJS_INTERNALS_TREE = current.__PRIVATE_NEXTJS_INTERNALS_TREE
    }
    return next
  }

  window.history.pushState = function (data: Record<string, unknown> | null, unused, url) {
    if (data?.__NA || data?._N) return originalPush(data, unused, url)
    if (url) syncedUrls.push(String(url))
    return originalPush(copyNextJsInternalHistoryState(data), unused, url)
  } as typeof window.history.pushState

  window.history.replaceState = function (data: Record<string, unknown> | null, unused, url) {
    if (data?.__NA || data?._N) return originalReplace(data, unused, url)
    if (url) syncedUrls.push(String(url))
    return originalReplace(copyNextJsInternalHistoryState(data), unused, url)
  } as typeof window.history.replaceState

  return {
    syncedUrls,
    restore() {
      window.history.pushState = originalPush
      window.history.replaceState = originalReplace
    },
  }
}

describe('commitBrowseUrl — same-page identity transitions', () => {
  let patch: ReturnType<typeof installNextHistoryPatch>

  beforeEach(() => {
    patch = installNextHistoryPatch()
    window.history.replaceState({ __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ['tree'] }, '', '/e-hentai')
  })

  afterEach(() => {
    patch.restore()
    vi.restoreAllMocks()
  })

  // Regression: the call passed window.history.state straight back, and every
  // App Router history entry carries __NA, so the patch bailed out and never
  // dispatched ACTION_RESTORE. useSearchParams kept the stale query, so
  // NavMemoryTracker never recorded an in-page tab or favcat change: after
  // popular -> favorites -> favcat 8 -> /library, the E-Hentai nav tab restored
  // popular instead of favcat 8.
  it('lets the App Router observe the new URL instead of opting out of the sync', () => {
    commitBrowseUrl('/e-hentai?tab=favorites&favcat=8', 'replace')

    expect(patch.syncedUrls).toEqual(['/e-hentai?tab=favorites&favcat=8'])
  })

  it('keeps the App Router internals on the entry it writes', () => {
    commitBrowseUrl('/e-hentai?tab=favorites', 'replace')

    expect(window.history.state.__NA).toBe(true)
    expect(window.history.state.__PRIVATE_NEXTJS_INTERNALS_TREE).toEqual(['tree'])
  })

  it('replace mode does not add a history entry', () => {
    const before = window.history.length
    commitBrowseUrl('/e-hentai?tab=favorites', 'replace')
    expect(window.history.length).toBe(before)
    expect(window.location.search).toBe('?tab=favorites')
  })

  it('push mode adds a history entry so the previous identity stays reachable', () => {
    const before = window.history.length
    commitBrowseUrl('/e-hentai?tab=favorites', 'push')
    expect(window.history.length).toBe(before + 1)
    expect(window.location.search).toBe('?tab=favorites')
  })
})
