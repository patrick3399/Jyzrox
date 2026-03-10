/**
 * Browse page — Vitest test suite
 *
 * Covers:
 *   Renders search input on mount
 *   Renders tab buttons (search / popular / toplist)
 *   Default tab is search (EH search results container visible)
 *   Clicking Popular tab switches to popular view
 *   Clicking Toplist tab switches to toplist view
 *   Loading state renders a spinner
 *   Gallery titles rendered when search hook returns results
 *   Clicking a gallery card navigates to /browse/{gid}/{token}
 *
 * Mock strategy:
 *   - next/navigation → stub useRouter and useSearchParams
 *   - @/hooks/useGalleries → control hook return values per test
 *   - @/lib/api → stub api.download.enqueue, api.settings.*, api.savedSearches.*
 *   - sonner → stub toast
 *   - @/components/* → stub heavy sub-components to simple divs
 *   - @/lib/i18n → returns key as-is for predictable text assertions
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const {
  mockEnqueue,
  mockToastSuccess,
  mockToastError,
  mockUseEhSearch,
  mockUseEhPopular,
  mockUseEhToplist,
  mockUseEhFavorites,
  mockRouterPush,
} = vi.hoisted(() => ({
  mockEnqueue: vi.fn(),
  mockToastSuccess: vi.fn(),
  mockToastError: vi.fn(),
  mockUseEhSearch: vi.fn(),
  mockUseEhPopular: vi.fn(),
  mockUseEhToplist: vi.fn(),
  mockUseEhFavorites: vi.fn(),
  mockRouterPush: vi.fn(),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush, replace: vi.fn() }),
  useSearchParams: () => ({ get: (_key: string) => null }),
}))

vi.mock('sonner', () => ({
  toast: {
    success: mockToastSuccess,
    error: mockToastError,
  },
}))

vi.mock('@/lib/api', () => ({
  api: {
    download: {
      enqueue: mockEnqueue,
    },
    settings: {
      getCredentials: vi.fn().mockResolvedValue({
        ehentai: { configured: false },
        pixiv: { configured: false },
      }),
    },
    savedSearches: {
      list: vi.fn().mockResolvedValue({ searches: [] }),
      create: vi.fn().mockResolvedValue({}),
      delete: vi.fn().mockResolvedValue({}),
    },
  },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/hooks/useGalleries', () => ({
  useEhSearch: mockUseEhSearch,
  useEhPopular: mockUseEhPopular,
  useEhToplist: mockUseEhToplist,
  useEhFavorites: mockUseEhFavorites,
}))

// Stub heavy sub-components
vi.mock('@/components/Pagination', () => ({
  Pagination: () => <div data-testid="pagination" />,
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}))

vi.mock('@/components/RatingStars', () => ({
  RatingStars: ({ rating }: { rating: number }) => <span>{rating}</span>,
}))

vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: ({ items, renderItem }: { items: unknown[]; renderItem: (item: unknown, index: number) => React.ReactNode }) => (
    <div data-testid="virtual-grid">{items.map((item, i) => renderItem(item, i))}</div>
  ),
}))

// ── Import page after mocks ──────────────────────────────────────────

import BrowsePage from '@/app/e-hentai/page'

// ── Factories ─────────────────────────────────────────────────────────

function makeEhGallery(id: number) {
  return {
    gid: id,
    token: `tok${id}`,
    title: `Gallery ${id}`,
    title_jpn: '',
    category: 'manga',
    thumb: '',
    uploader: 'user',
    posted: 0,
    filecount: 20,
    rating: 4.5,
    tags: [],
    url: `https://e-hentai.org/g/${id}/tok${id}/`,
    favorited: false,
    eh_favorited: false,
    pages: 20,
  }
}

const EMPTY_SEARCH_RESULT = { galleries: [], total: 0, page: 0 }
const EMPTY_TOPLIST_RESULT = { galleries: [], total: 0, page: 0 }

// ── Default hook return values ─────────────────────────────────────────

function setDefaultHooks() {
  mockUseEhSearch.mockReturnValue({ data: EMPTY_SEARCH_RESULT, isLoading: false, error: null })
  mockUseEhPopular.mockReturnValue({ data: { galleries: [], total: 0 }, isLoading: false, error: null })
  mockUseEhToplist.mockReturnValue({ data: EMPTY_TOPLIST_RESULT, isLoading: false, error: null })
  mockUseEhFavorites.mockReturnValue({
    data: { galleries: [], total: 0, has_next: false, has_prev: false, next_cursor: null, prev_cursor: null, categories: [] },
    isLoading: false,
    error: null,
  })
}

// ── Setup / Teardown ──────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  setDefaultHooks()
  localStorage.clear()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('Browse page — initial render', () => {
  it('test_browse_renders_searchInput', async () => {
    await act(async () => {
      render(<BrowsePage />)
    })
    // The search input is identifiable by its placeholder
    const input = screen.getByPlaceholderText('browse.searchPlaceholder')
    expect(input).toBeInTheDocument()
  })

  it('test_browse_renders_popularTabButton', async () => {
    await act(async () => {
      render(<BrowsePage />)
    })
    expect(screen.getByText('browse.popularTab')).toBeInTheDocument()
  })

  it('test_browse_renders_toplistTabButton', async () => {
    await act(async () => {
      render(<BrowsePage />)
    })
    expect(screen.getByText('browse.toplistTab')).toBeInTheDocument()
  })

  it('test_browse_renders_searchTabButton', async () => {
    await act(async () => {
      render(<BrowsePage />)
    })
    expect(screen.getByText('browse.searchTab')).toBeInTheDocument()
  })
})

describe('Browse page — loading state', () => {
  it('test_browse_loading_rendersSpinner', async () => {
    mockUseEhSearch.mockReturnValue({ data: undefined, isLoading: true, error: null })
    await act(async () => {
      render(<BrowsePage />)
    })
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
  })

  it('test_browse_notLoading_doesNotRenderSpinner', async () => {
    await act(async () => {
      render(<BrowsePage />)
    })
    expect(screen.queryByTestId('loading-spinner')).not.toBeInTheDocument()
  })
})

describe('Browse page — gallery results', () => {
  it('test_browse_withResults_rendersGalleryTitles', async () => {
    mockUseEhSearch.mockReturnValue({
      data: { galleries: [makeEhGallery(1), makeEhGallery(2)], total: 2, page: 0 },
      isLoading: false,
      error: null,
    })
    await act(async () => {
      render(<BrowsePage />)
    })
    expect(screen.getByText('Gallery 1')).toBeInTheDocument()
    expect(screen.getByText('Gallery 2')).toBeInTheDocument()
  })

  it('test_browse_withResults_rendersTotalCount', async () => {
    mockUseEhSearch.mockReturnValue({
      data: { galleries: [makeEhGallery(1)], total: 42, page: 0 },
      isLoading: false,
      error: null,
    })
    await act(async () => {
      render(<BrowsePage />)
    })
    expect(screen.getByText(/browse\.resultsCount/)).toBeInTheDocument()
  })
})

describe('Browse page — tab switching', () => {
  it('test_browse_clickPopularTab_switchesToPopularView', async () => {
    const user = userEvent.setup()
    mockUseEhPopular.mockReturnValue({
      data: { galleries: [makeEhGallery(99)], total: 1 },
      isLoading: false,
      error: null,
    })
    await act(async () => {
      render(<BrowsePage />)
    })
    await act(async () => {
      await user.click(screen.getByText('browse.popularTab'))
    })
    expect(screen.getByText('Gallery 99')).toBeInTheDocument()
  })

  it('test_browse_clickToplistTab_doesNotShowSearchResults', async () => {
    const user = userEvent.setup()
    mockUseEhSearch.mockReturnValue({
      data: { galleries: [makeEhGallery(1)], total: 1, page: 0 },
      isLoading: false,
      error: null,
    })
    mockUseEhToplist.mockReturnValue({
      data: { galleries: [], total: 0, page: 0 },
      isLoading: false,
      error: null,
    })
    await act(async () => {
      render(<BrowsePage />)
    })
    await act(async () => {
      await user.click(screen.getByText('browse.toplistTab'))
    })
    // Search result should no longer be visible after switching tab
    expect(screen.queryByText('Gallery 1')).not.toBeInTheDocument()
  })

  it('test_browse_clickSearchTab_afterPopular_showsSearchInputAgain', async () => {
    const user = userEvent.setup()
    await act(async () => {
      render(<BrowsePage />)
    })
    await act(async () => {
      await user.click(screen.getByText('browse.popularTab'))
    })
    await act(async () => {
      await user.click(screen.getByText('browse.searchTab'))
    })
    expect(screen.getByPlaceholderText('browse.searchPlaceholder')).toBeInTheDocument()
  })
})

describe('Browse page — gallery navigation', () => {
  it('test_browse_clickGallery_navigatesToDetailPage', async () => {
    const user = userEvent.setup()
    mockUseEhSearch.mockReturnValue({
      data: { galleries: [makeEhGallery(1)], total: 1, page: 0 },
      isLoading: false,
      error: null,
    })
    await act(async () => {
      render(<BrowsePage />)
    })
    await act(async () => {
      await user.click(screen.getByText('Gallery 1'))
    })
    expect(mockRouterPush).toHaveBeenCalledWith('/e-hentai/1/tok1')
  })
})
