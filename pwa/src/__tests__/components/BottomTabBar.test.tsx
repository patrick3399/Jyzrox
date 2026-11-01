import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const pushMock = vi.fn()
let currentPath = '/pixiv'

vi.mock('next/navigation', () => ({
  usePathname: () => currentPath,
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'en' as const, setLocale: vi.fn() }),
}))

import { BottomTabBar } from '@/components/BottomTabBar'
import { rememberLocation, getTabHref, consumeTabRestore } from '@/lib/navMemory'

const ROOTS = ['/e-hentai', '/pixiv', '/library', '/queue']

describe('BottomTabBar tab memory', () => {
  beforeEach(() => {
    sessionStorage.clear()
    pushMock.mockClear()
    currentPath = '/pixiv'
  })

  it('links a non-active tab to its remembered url', () => {
    rememberLocation(ROOTS, '/e-hentai', 'fav=1&page=3')
    render(<BottomTabBar onMoreClick={() => {}} />)
    const link = screen.getByRole('link', { name: /e-?hentai/i })
    expect(link).toHaveAttribute('href', '/e-hentai?fav=1&page=3')
  })

  it('single tap on the active tab scrolls to top without navigating', () => {
    const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    render(<BottomTabBar onMoreClick={() => {}} />)
    const link = screen.getByRole('link', { name: /pixiv/i })
    fireEvent.click(link)
    expect(scrollSpy).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }))
    expect(pushMock).not.toHaveBeenCalled()
  })

  it('double tap on the active tab resets it to the bare root and clears memory', () => {
    rememberLocation(ROOTS, '/pixiv', 'tab=feed')
    render(<BottomTabBar onMoreClick={() => {}} />)
    const link = screen.getByRole('link', { name: /pixiv/i })
    fireEvent.click(link)
    fireEvent.click(link)
    expect(pushMock).toHaveBeenCalledWith('/pixiv')
    expect(getTabHref('/pixiv')).toBe('/pixiv')
  })

  it('suppresses native long-press callouts on the app control surface', () => {
    render(<BottomTabBar onMoreClick={() => {}} />)
    const navigation = screen.getByRole('navigation')
    expect(navigation).toHaveClass('app-touch-controls')

    const contextMenu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    fireEvent(navigation, contextMenu)
    expect(contextMenu.defaultPrevented).toBe(true)
  })

  // Regression: on a deep page of the active section a single tap only scrolled
  // to top and a double tap cleared memory and pushed the bare root, so the tab
  // never took the user back to the list they came from.
  describe('on a deep page of the active section', () => {
    beforeEach(() => {
      rememberLocation(ROOTS, '/pixiv', 'tab=bookmarks')
      rememberLocation(ROOTS, '/pixiv/illust/1', '')
      currentPath = '/pixiv/illust/1'
    })

    it('links the active tab to the remembered list url, not the deep page it is on', () => {
      render(<BottomTabBar onMoreClick={() => {}} />)
      const link = screen.getByRole('link', { name: /pixiv/i })
      expect(link).toHaveAttribute('href', '/pixiv?tab=bookmarks')
    })

    it('a tap navigates to the remembered list instead of only scrolling to top', () => {
      const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
      scrollSpy.mockClear() // the spy outlives earlier tests in this file
      render(<BottomTabBar onMoreClick={() => {}} />)
      const link = screen.getByRole('link', { name: /pixiv/i })

      // Not handled by the bar: the Link is left to navigate to its href.
      let handledByBar = false
      link.addEventListener('click', (event) => {
        handledByBar = event.defaultPrevented
      })
      fireEvent.click(link)

      expect(scrollSpy).not.toHaveBeenCalled()
      expect(pushMock).not.toHaveBeenCalled()
      expect(handledByBar).toBe(false)
    })

    it('a double tap does not wipe the remembered list or push the bare root', () => {
      vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
      render(<BottomTabBar onMoreClick={() => {}} />)
      const link = screen.getByRole('link', { name: /pixiv/i })

      fireEvent.click(link)
      fireEvent.click(link)

      expect(pushMock).not.toHaveBeenCalledWith('/pixiv')
      expect(getTabHref('/pixiv')).not.toBe('/pixiv')
      expect(link).toHaveAttribute('href', '/pixiv?tab=bookmarks')
    })

    it('does not arm tab-restore for the list it climbs to', () => {
      render(<BottomTabBar onMoreClick={() => {}} />)
      fireEvent.click(screen.getByRole('link', { name: /pixiv/i }))

      expect(consumeTabRestore('/pixiv?tab=bookmarks')).toBe(false)
    })
  })

  // Regression: isActive used pathname.startsWith(href) with no `/` boundary, so
  // /pixiv-archive lit up (and was treated as inside) the /pixiv section.
  it('does not treat a sibling path that merely shares the prefix as inside the section', () => {
    currentPath = '/pixivx'
    render(<BottomTabBar onMoreClick={() => {}} />)
    const link = screen.getByRole('link', { name: /pixiv/i })
    expect(link.className).not.toContain('text-vault-accent')
    expect(link.className).toContain('text-vault-text-secondary')
  })

  it('marks the tab active on the root and on a nested path', () => {
    render(<BottomTabBar onMoreClick={() => {}} />)
    expect(screen.getByRole('link', { name: /pixiv/i }).className).toContain('text-vault-accent')
  })
})
