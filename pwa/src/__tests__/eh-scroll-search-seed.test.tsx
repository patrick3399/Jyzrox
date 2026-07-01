/**
 * Regression test: in infinite-scroll mode, searching from the default
 * `popular` tab must display results.
 *
 * Bug: the scroll-mode seed effect was gated on `activeTab === 'search'`, but
 * a plain search from the search box sets `searchQuery` without switching the
 * tab away from the default `popular`. As a result `scrollGalleries` was never
 * seeded and the search results rendered empty — even though SWR had the data.
 * The render gate uses `searchQuery || activeTab === 'search'`, so the seed
 * gate must match it.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// ── Mock next/navigation: URL carries ?q= but no tab (default = popular) ──

const mockSearchParams = new URLSearchParams('q=test')

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => mockSearchParams,
}))

// ── Mock the EH data hooks. Search returns one gallery. ──

const SEARCH_GALLERY = {
  gid: 12345,
  token: 'abc123',
  title: 'ScrollResultGallery',
  title_jpn: '',
  category: 'doujinshi',
  thumb: '',
  uploader: 'uploader',
  posted_at: 1700000000,
  pages: 20,
  rating: 4.5,
  tags: [],
  expunged: false,
}

vi.mock('@/hooks/useGalleries', () => ({
  useEhSearch: () => ({
    data: { galleries: [SEARCH_GALLERY], next_gid: 99999 },
    isLoading: false,
    error: undefined,
  }),
  useEhFavorites: () => ({ data: undefined, isLoading: false, error: undefined }),
  useEhPopular: () => ({ data: { galleries: [] }, isLoading: false, error: undefined }),
  useEhToplist: () => ({ data: undefined, isLoading: false, error: undefined }),
}))

vi.mock('@/hooks/useSubscriptions', () => ({
  useCreateSubscription: () => ({ trigger: vi.fn(), isMutating: false }),
}))

vi.mock('swr', () => ({
  default: () => ({ data: { ehentai: { configured: true } }, isLoading: false }),
}))

vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: -1 }),
}))

vi.mock('@/hooks/useScrollRestore', () => ({
  useScrollRestore: () => {},
}))

// VirtualGrid pulls in ResizeObserver (unavailable in jsdom); render items directly.
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: ({
    items,
    renderItem,
  }: {
    items: unknown[]
    renderItem: (item: unknown, index: number) => React.ReactNode
  }) => <div data-testid="grid">{items.map((it, i) => renderItem(it, i))}</div>,
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))

vi.mock('@/components/CredentialBanner', () => ({
  CredentialBanner: () => <div data-testid="cred-banner" />,
}))

vi.mock('@/components/RatingStars', () => ({
  RatingStars: ({ rating }: { rating: number }) => <span data-testid="rating">{rating}</span>,
}))

vi.mock('@/components/Paginator', () => ({
  default: () => <div data-testid="paginator" />,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/lib/api', () => ({
  api: {
    savedSearches: { list: vi.fn().mockResolvedValue({ searches: [] }) },
    settings: { getCredentials: vi.fn().mockResolvedValue({ ehentai: { configured: true } }) },
    eh: { search: vi.fn() },
  },
}))

describe('E-Hentai infinite scroll search seeding', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    localStorage.setItem('browse_load_mode', 'scroll')
  })

  it('shows search results in scroll mode when searching from the default popular tab', async () => {
    const { default: Page } = await import('@/app/e-hentai/page')
    render(<Page />)

    // The gallery from useEhSearch must be rendered; before the fix scrollGalleries
    // was never seeded (activeTab stayed 'popular') so this text was absent.
    expect(await screen.findByText('ScrollResultGallery')).toBeDefined()
  })
})
