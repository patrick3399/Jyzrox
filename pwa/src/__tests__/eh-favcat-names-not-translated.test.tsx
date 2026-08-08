/**
 * Regression test: E-Hentai favourite category labels must never be localized.
 *
 * Bug (a0ea0f9 "fix(i18n): localize remaining PWA surfaces"): the favourites
 * pill fallback and the detail-page favourite picker were routed through
 * t('browse.favoriteCategory'). Under a non-English locale the pills rendered
 * "我的最愛 0-9" on mount and then flipped to the real E-Hentai names once
 * getFavorites() resolved. Favcat names are remote E-Hentai data, so the
 * fallback must mirror upstream's own "Favorites N" label instead.
 */

import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { loadLocale, setLocale } from '@/lib/i18n'

let favCategories: { index: number; name: string; count: number }[] = []

vi.mock('next/navigation', () => ({
  useParams: () => ({ gid: '12345', token: 'abc123' }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  usePathname: () => '/e-hentai/12345/abc123',
  useSearchParams: () => new URLSearchParams(searchStr),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))

let searchStr = 'tab=favorites'

vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        has_prev: false,
        next_cursor: null,
        prev_cursor: null,
        categories: favCategories,
      })),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
      addFavorite: vi.fn(),
      removeFavorite: vi.fn(),
      getPreviews: vi.fn(),
    },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
    history: { recordBrowse: vi.fn().mockResolvedValue({}) },
  },
}))

// ── Detail-page-only deps ────────────────────────────────────────────

vi.mock('@/hooks/useGalleries', () => ({
  useEhGallery: () => ({
    data: {
      gid: 12345,
      token: 'abc123',
      title: 'Test Gallery',
      title_jpn: '',
      category: 'Doujinshi',
      thumb: '',
      uploader: 'test',
      posted_at: 1700000000,
      pages: 10,
      rating: 4.5,
      tags: [],
      expunged: false,
    },
    error: undefined,
  }),
  useEhGalleryPreviews: () => ({ data: null }),
  useEhGalleryComments: () => ({ data: null, isLoading: false }),
  useEhGalleryImagesPaginated: () => ({
    getToken: () => null,
    getPreview: () => null,
    ensureRange: vi.fn(),
    isLoading: false,
  }),
}))

vi.mock('@/hooks/useTagTranslations', () => ({
  useTagTranslations: () => ({ translateTag: (tag: string) => tag }),
}))

vi.mock('dompurify', () => ({ default: { sanitize: (s: string) => s } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import BrowsePage from '@/app/e-hentai/page'
import DetailPage from '@/app/e-hentai/[gid]/[token]/page'

beforeAll(async () => {
  await loadLocale('zh-TW')
  setLocale('zh-TW')
})

beforeEach(() => {
  searchStr = 'tab=favorites'
  favCategories = []
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'list')
  vi.clearAllMocks()
})

describe('E-Hentai favourite category names stay untranslated under a zh-TW locale', () => {
  it('renders the upstream "Favorites N" fallback pill, never a localized label', async () => {
    render(<BrowsePage />)

    expect(await screen.findByText('Favorites 0')).toBeDefined()
    expect(screen.getByText('Favorites 9')).toBeDefined()
    expect(screen.queryByText('我的最愛 0')).toBeNull()
  })

  it('keeps showing the untranslated fallback after the favourites fetch resolves', async () => {
    render(<BrowsePage />)

    await waitFor(() => {
      expect(screen.getByText('Favorites 0')).toBeDefined()
    })
    // The category list came back empty — the pills must not flip languages.
    expect(screen.queryByText('我的最愛 0')).toBeNull()
  })

  it('prefers the real E-Hentai category name once it arrives', async () => {
    favCategories = [{ index: 0, name: 'Doujin backlog', count: 3 }]

    render(<BrowsePage />)

    expect(await screen.findByText('Doujin backlog')).toBeDefined()
    expect(screen.queryByText('Favorites 0')).toBeNull()
  })

  it('labels the detail-page favourite picker with untranslated names', async () => {
    render(<DetailPage />)

    fireEvent.click(await screen.findByText('♡'))

    expect(await screen.findByText('Favorites 0')).toBeDefined()
    expect(screen.getByText('Favorites 9')).toBeDefined()
    expect(screen.queryByText('我的最愛 0')).toBeNull()
  })
})
