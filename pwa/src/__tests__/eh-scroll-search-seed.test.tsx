/**
 * Regression test: searching from the default `popular` tab must display results.
 *
 * Original bug (commit 8589088): the scroll-mode seed effect was gated on
 * `activeTab === 'search'`, but a plain search from the search box set
 * `searchQuery` without switching the tab away from `popular`, so the scroll
 * list was never seeded and results rendered empty.
 *
 * New model: a URL carrying `q=` derives the `search` identity, and the single
 * seed effect fetches the first page via `api.eh.search`. This test pins that a
 * URL-driven query seeds and renders without any tab plumbing.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

// URL carries ?q= but no explicit tab (default identity resolves to `search`).
const mockSearchParams = new URLSearchParams('q=test')
const replaceMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock, back: vi.fn() }),
  useSearchParams: () => mockSearchParams,
}))

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

vi.mock('@/hooks/useSubscriptions', () => ({
  useCreateSubscription: () => ({ trigger: vi.fn(), isMutating: false }),
  useSubscriptions: () => ({ data: { subscriptions: [] }, mutate: vi.fn() }),
}))

vi.mock('swr', () => ({
  default: () => ({ data: { ehentai: { configured: true } }, isLoading: false }),
}))

vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: -1 }),
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

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

const searchMock = vi.fn().mockResolvedValue({
  galleries: [SEARCH_GALLERY],
  total: 1,
  page: 0,
  next_gid: 99999,
})

vi.mock('@/lib/api', () => ({
  api: {
    savedSearches: { list: vi.fn().mockResolvedValue({ searches: [] }) },
    settings: { getCredentials: vi.fn().mockResolvedValue({ ehentai: { configured: true } }) },
    eh: {
      search: (...args: unknown[]) => searchMock(...args),
      getFavorites: vi.fn(),
      getPopular: vi.fn().mockResolvedValue({ galleries: [], total: 0 }),
      getToplist: vi.fn(),
    },
  },
}))

describe('E-Hentai search seeding', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    searchMock.mockClear()
    replaceMock.mockClear()
    mockSearchParams.delete('tab')
    mockSearchParams.delete('adv_open')
    mockSearchParams.delete('minrating')
    mockSearchParams.set('q', 'test')
  })

  it('seeds and shows search results when the URL carries a query', async () => {
    const { default: Page } = await import('@/app/e-hentai/page')
    render(<Page />)

    expect(await screen.findByText('ScrollResultGallery')).toBeDefined()
    await waitFor(() =>
      expect(searchMock).toHaveBeenCalledWith(
        expect.objectContaining({ q: 'test' }),
        expect.anything(),
      ),
    )
  })

  it('applies a saved-search URL that changes while the page stays mounted', async () => {
    const { default: Page } = await import('@/app/e-hentai/page')
    mockSearchParams.delete('q')
    const view = render(<Page />)

    mockSearchParams.set('q', 'language:chinese')
    mockSearchParams.set('adv_open', '1')
    mockSearchParams.set('minrating', '5')
    view.rerender(<Page />)

    await waitFor(() =>
      expect(searchMock).toHaveBeenCalledWith(
        expect.objectContaining({
          q: 'language:chinese',
          advance: true,
          min_rating: 5,
        }),
        expect.anything(),
      ),
    )
    expect(screen.getByText('browse.minRating')).toBeInTheDocument()
  })

  it('clearing a search also clears its advanced filters', async () => {
    const { default: Page } = await import('@/app/e-hentai/page')
    mockSearchParams.set('q', 'language:chinese')
    mockSearchParams.set('adv_open', '1')
    mockSearchParams.set('minrating', '5')
    render(<Page />)

    await screen.findByText('ScrollResultGallery')
    fireEvent.click(screen.getByRole('button', { name: 'browse.clearSearch' }))

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith('/e-hentai?tab=popular', { scroll: false }),
    )
    const urls = replaceMock.mock.calls.map(([url]) => String(url))
    expect(urls.at(-1)).not.toMatch(/q=|adv_open=|minrating=/)
  })
})
