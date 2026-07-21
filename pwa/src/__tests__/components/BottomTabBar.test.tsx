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
import { rememberLocation, getTabHref } from '@/lib/navMemory'

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
})
