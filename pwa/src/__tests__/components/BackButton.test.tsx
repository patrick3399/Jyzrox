import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockRouter = { back: vi.fn(), push: vi.fn() }

vi.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { BackButton } from '@/components/BackButton'

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
