import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
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
})
