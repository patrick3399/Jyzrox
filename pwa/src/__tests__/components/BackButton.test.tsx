import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockRouter = { back: vi.fn(), push: vi.fn(), replace: vi.fn() }

vi.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
  usePathname: () => '/',
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { BackButton } from '@/components/BackButton'
import { rememberLocation, markTabRestore } from '@/lib/navMemory'

// Some tests below replace window.history with a bare {length} stub; keep the
// real object around so URL-dependent tests can restore it.
const realHistory = window.history

describe('BackButton — positioning', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('test_backButton_noLgStaticClass', () => {
    render(<BackButton fallback="/e-hentai" />)
    const btn = screen.getByRole('button', { name: /common\.back/i })
    expect(btn.className).not.toContain('lg:static')
  })

  it('test_backButton_alwaysHasFixedClass', () => {
    render(<BackButton fallback="/e-hentai" />)
    const btn = screen.getByRole('button', { name: /common\.back/i })
    expect(btn.className).toContain('fixed')
  })

  it('test_backButton_click_callsRouterBack_whenHistoryExists', async () => {
    Object.defineProperty(window, 'history', {
      value: { length: 2 },
      writable: true,
      configurable: true,
    })

    render(<BackButton fallback="/e-hentai" />)
    await userEvent.click(screen.getByRole('button', { name: /common\.back/i }))

    expect(mockRouter.back).toHaveBeenCalledTimes(1)
    expect(mockRouter.push).not.toHaveBeenCalled()
  })
})

describe('BackButton — hierarchical up after a tab-restore arrival', () => {
  // Regression: favorites → gallery → /trash → (bottom tab restores the deep
  // gallery URL) → BackButton did history.back() and landed on /trash. When a
  // page is reached via tab restore, back must climb to the section's last
  // list-level URL instead of walking browser history out of the section.
  const ROOTS = ['/e-hentai', '/pixiv', '/library', '/queue']

  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    Object.defineProperty(window, 'history', {
      value: realHistory,
      writable: true,
      configurable: true,
    })
    realHistory.replaceState({}, '', '/e-hentai/123/abc?fav=1')
  })

  it('goes up to the remembered list URL when the page was reached via tab restore', () => {
    rememberLocation(ROOTS, '/e-hentai', 'tab=favorites')
    rememberLocation(ROOTS, '/e-hentai/123/abc', 'fav=1')
    markTabRestore('/e-hentai/123/abc?fav=1')

    render(<BackButton fallback="/e-hentai" />)
    fireEvent.click(screen.getByRole('button', { name: /common\.back/i }))

    expect(mockRouter.replace).toHaveBeenCalledWith('/e-hentai?tab=favorites')
    expect(mockRouter.back).not.toHaveBeenCalled()
  })

  // Regression: the climb used push, so the restored gallery stayed one step
  // forward in history — pressing back and then swiping back returned the user
  // to the very page they had just dismissed, and repeating it grew the stack
  // without bound. Climbing replaces the arrival entry instead.
  it('climbing up replaces the restored entry instead of stacking on top of it', () => {
    rememberLocation(ROOTS, '/e-hentai', 'tab=favorites')
    markTabRestore('/e-hentai/123/abc?fav=1')

    render(<BackButton fallback="/e-hentai" />)
    fireEvent.click(screen.getByRole('button', { name: /common\.back/i }))

    expect(mockRouter.push).not.toHaveBeenCalled()
    expect(mockRouter.replace).toHaveBeenCalledTimes(1)
  })

  it('falls back to the bare section root on tab-restore arrival without a list visit', () => {
    markTabRestore('/e-hentai/123/abc?fav=1')
    render(<BackButton fallback="/e-hentai" />)
    fireEvent.click(screen.getByRole('button', { name: /common\.back/i }))
    expect(mockRouter.replace).toHaveBeenCalledWith('/e-hentai')
    expect(mockRouter.back).not.toHaveBeenCalled()
  })

  it('ignores a stale mark pointing at a different URL', () => {
    markTabRestore('/e-hentai/999/zzz?fav=1')
    Object.defineProperty(window, 'history', {
      value: { length: 2 },
      writable: true,
      configurable: true,
    })
    render(<BackButton fallback="/e-hentai" />)
    fireEvent.click(screen.getByRole('button', { name: /common\.back/i }))
    expect(mockRouter.back).toHaveBeenCalledTimes(1)
    expect(mockRouter.push).not.toHaveBeenCalled()
  })

  it('the restore mark is one-shot: a second back uses history again', () => {
    rememberLocation(ROOTS, '/e-hentai', 'tab=favorites')
    markTabRestore('/e-hentai/123/abc?fav=1')
    render(<BackButton fallback="/e-hentai" />)
    const btn = screen.getByRole('button', { name: /common\.back/i })
    fireEvent.click(btn)
    expect(mockRouter.replace).toHaveBeenCalledWith('/e-hentai?tab=favorites')
    Object.defineProperty(window, 'history', {
      value: { length: 2 },
      writable: true,
      configurable: true,
    })
    fireEvent.click(btn)
    expect(mockRouter.back).toHaveBeenCalledTimes(1)
  })
})
