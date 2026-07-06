import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/novels/search',
}))

const h = vi.hoisted(() => ({
  hits: {
    hits: [{ path: '作品A/第01章.md', line: 4, text: '正文一段' }],
  },
}))

vi.mock('swr', () => ({
  default: (key: unknown) => (key ? { data: h.hits, isLoading: false } : { data: undefined, isLoading: false }),
}))
vi.mock('@/lib/api', () => ({ api: { novels: { search: vi.fn() } } }))

import NovelSearchPage from '@/app/novels/search/page'

describe('NovelSearchPage', () => {
  it('renders search hits after submitting a query', () => {
    render(<NovelSearchPage />)
    fireEvent.change(screen.getByPlaceholderText('novels.searchPlaceholder'), {
      target: { value: '正文' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'novels.search' }))
    expect(screen.getByText('正文一段')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /正文一段/ })
    expect(link.getAttribute('href')).toContain('/novels/')
    expect(link.getAttribute('href')).toContain('path=')
  })
})
