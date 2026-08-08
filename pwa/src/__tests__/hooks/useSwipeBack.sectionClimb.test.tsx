import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@testing-library/react'

const mockRouter = { back: vi.fn(), push: vi.fn(), replace: vi.fn() }
let mockPathname = '/e-hentai/123/abc'

vi.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
  usePathname: () => mockPathname,
}))

import { useSwipeBack } from '@/hooks/useSwipeBack'
import { rememberLocation, markTabRestore } from '@/lib/navMemory'

const ROOTS = ['/e-hentai', '/pixiv', '/library', '/queue']

function Harness() {
  useSwipeBack()
  return null
}

/** jsdom's TouchEvent constructor drops the touch lists, so build the event and
 *  attach them directly. */
function touchEvent(type: string, key: 'touches' | 'changedTouches', x: number, y: number): Event {
  const event = new Event(type, { bubbles: true })
  Object.defineProperty(event, key, { value: [{ clientX: x, clientY: y }] })
  return event
}

/** Left-edge horizontal drag that satisfies EDGE_THRESHOLD/MIN_SWIPE/DIR_RATIO. */
function edgeSwipeRight() {
  act(() => {
    document.dispatchEvent(touchEvent('touchstart', 'touches', 4, 300))
    document.dispatchEvent(touchEvent('touchend', 'changedTouches', 180, 305))
  })
}

describe('useSwipeBack — staying inside the section after a tab restore', () => {
  const realMatchMedia = window.matchMedia

  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    mockPathname = '/e-hentai/123/abc'
    // The gesture only arms itself in a standalone (home-screen) app, which is
    // exactly the case where no browser back affordance exists.
    window.matchMedia = ((query: string) =>
      ({
        matches: query === '(display-mode: standalone)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList) as typeof window.matchMedia
    // jsdom starts at history.length === 1, which is the "nothing to go back to"
    // branch. Grow the stack so these tests exercise the normal in-app case.
    window.history.pushState({}, '', '/library')
    window.history.pushState({}, '', '/e-hentai/123/abc?fav=1')
  })

  afterEach(() => {
    window.matchMedia = realMatchMedia
  })

  // Regression: eh popular -> favorites -> favcat 8 -> gallery A -> tag search
  // -> gallery B -> /library -> (nav tab restores the deep gallery B URL).
  // BackButton climbed to the E-Hentai list, but the edge swipe called
  // router.back() directly and landed on /library — leaving the section through
  // the page the user had merely detoured via. In a standalone app the swipe is
  // the only back affordance on a page without a back FAB.
  it('edge swipe on a tab-restored deep page climbs to the section list instead of leaving the section', () => {
    rememberLocation(ROOTS, '/e-hentai', 'q=tag')
    rememberLocation(ROOTS, '/e-hentai/123/abc', 'fav=1')
    markTabRestore('/e-hentai/123/abc?fav=1')

    render(<Harness />)
    edgeSwipeRight()

    expect(mockRouter.back).not.toHaveBeenCalled()
    expect(mockRouter.replace).toHaveBeenCalledWith('/e-hentai?q=tag')
  })

  it('edge swipe without a restore mark still walks browser history', () => {
    rememberLocation(ROOTS, '/e-hentai', 'q=tag')

    render(<Harness />)
    edgeSwipeRight()

    expect(mockRouter.back).toHaveBeenCalledTimes(1)
    expect(mockRouter.replace).not.toHaveBeenCalled()
    expect(mockRouter.push).not.toHaveBeenCalled()
  })

  it('the restore mark is one-shot: a second edge swipe walks history', () => {
    rememberLocation(ROOTS, '/e-hentai', 'q=tag')
    markTabRestore('/e-hentai/123/abc?fav=1')

    render(<Harness />)
    edgeSwipeRight()
    expect(mockRouter.replace).toHaveBeenCalledWith('/e-hentai?q=tag')

    edgeSwipeRight()
    expect(mockRouter.back).toHaveBeenCalledTimes(1)
  })
})
