import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// The bug this guards: novel sub-pages only had a top-of-page back link, so you
// had to scroll to the top to leave a long chapter/list. They must now carry the
// shared BackButton FAB (fixed, always reachable) like every other detail page —
// and it must climb the hierarchy (toParent), not replay browser history.

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

const nav = vi.hoisted(() => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }))
vi.mock('next/navigation', () => ({
  useRouter: () => nav,
  usePathname: () => '/novels/作品A/第01章',
  useParams: () => ({ work: '作品A', chapter: '第01章' }),
  useSearchParams: () => new URLSearchParams('path=作品A/第01章.md'),
}))

vi.mock('swr', () => ({
  default: () => ({ data: { chapters: [], hits: [] }, isLoading: false }),
  mutate: vi.fn(),
}))

vi.mock('@/hooks/useProfile', () => ({ useProfile: () => ({ data: { role: 'admin' } }) }))

vi.mock('@/lib/api', () => ({
  api: { novels: { listChapters: vi.fn(), search: vi.fn() } },
}))

// Heavy reader/editor internals are irrelevant to back-nav; stub them out.
vi.mock('@/components/novels/Reader', () => ({ Reader: () => <div data-testid="reader" /> }))
vi.mock('@/components/novels/Editor', () => ({ Editor: () => <div /> }))
vi.mock('@/components/novels/HistoryPanel', () => ({ HistoryPanel: () => <div /> }))

import NovelChapterPage from '@/app/novels/[work]/[chapter]/page'
import NovelWorkPage from '@/app/novels/[work]/page'
import NovelSearchPage from '@/app/novels/search/page'

const backFab = () => screen.getByRole('button', { name: /common\.back/i })

describe('novel pages carry the shared BackButton FAB (climbs the hierarchy)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('chapter (reader) page: back climbs to the work chapter list, not history', () => {
    render(<NovelChapterPage />)
    fireEvent.click(backFab())
    expect(nav.push).toHaveBeenCalledWith('/novels/%E4%BD%9C%E5%93%81A')
    expect(nav.back).not.toHaveBeenCalled()
  })

  it('work (chapter list) page: back climbs to /novels', () => {
    render(<NovelWorkPage />)
    fireEvent.click(backFab())
    expect(nav.push).toHaveBeenCalledWith('/novels')
    expect(nav.back).not.toHaveBeenCalled()
  })

  it('search page: back climbs to /novels', () => {
    render(<NovelSearchPage />)
    fireEvent.click(backFab())
    expect(nav.push).toHaveBeenCalledWith('/novels')
    expect(nav.back).not.toHaveBeenCalled()
  })
})
