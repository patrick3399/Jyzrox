import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// The bug this guards: novel sub-pages only had a top-of-page back link, so you
// had to scroll to the top to leave a long chapter/list. They must now carry the
// shared BackButton FAB (fixed, always reachable) like every other detail page.

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
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

describe('novel pages carry the shared BackButton FAB', () => {
  it('chapter (reader) page has the back FAB', () => {
    render(<NovelChapterPage />)
    expect(backFab()).toBeInTheDocument()
  })

  it('work (chapter list) page has the back FAB', () => {
    render(<NovelWorkPage />)
    expect(backFab()).toBeInTheDocument()
  })

  it('search page has the back FAB', () => {
    render(<NovelSearchPage />)
    expect(backFab()).toBeInTheDocument()
  })
})
