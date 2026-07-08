import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

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
  current: null as { hits: Array<{ path: string; line: number; text: string; category?: string }> } | null,
  hits: {
    hits: [{ path: '作品A/第01章.md', line: 4, text: '正文一段' }],
  },
  categoryHits: {
    hits: [
      { path: '作品A/設定/角色卡.md', line: 0, text: '設定筆記內容', category: 'setting' },
      { path: '作品A/廢案/舊稿.md', line: 0, text: '廢案內容', category: 'scrap' },
    ],
  },
}))
h.current = h.hits

vi.mock('swr', () => ({
  default: (key: unknown) => (key ? { data: h.current, isLoading: false } : { data: undefined, isLoading: false }),
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

  it('shows a category badge only for a scrap hit, not for a setting hit', () => {
    h.current = h.categoryHits
    render(<NovelSearchPage />)
    fireEvent.change(screen.getByPlaceholderText('novels.searchPlaceholder'), {
      target: { value: '設定' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'novels.search' }))

    const settingItem = screen.getByText('設定筆記內容').closest('li')
    const scrapItem = screen.getByText('廢案內容').closest('li')
    expect(settingItem).not.toBeNull()
    expect(scrapItem).not.toBeNull()

    expect(within(settingItem as HTMLElement).queryByText(/^novels\.category/)).not.toBeInTheDocument()
    expect(within(scrapItem as HTMLElement).getByText('novels.categoryScrap')).toBeInTheDocument()
  })
})
