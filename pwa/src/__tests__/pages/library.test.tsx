/**
 * Library page — Vitest test suite
 *
 * Covers:
 *   Renders page title
 *   Renders search input placeholder
 *   Renders sort dropdown with correct options
 *   Renders source filter dropdown
 *   Renders favorites-only checkbox
 *   Empty library shows empty state (no gallery cards)
 *   Gallery cards rendered when data contains galleries
 *   Loading state shows spinner
 *   Error state shows error message
 *   Sort dropdown change updates sort state (hook called with new sort)
 *   Source dropdown change updates source filter
 *   Include-tag input + button adds tag chip
 *   Exclude-tag input + button adds tag chip
 *
 * Mock strategy:
 *   - @/hooks/useGalleries → control hook return values per test
 *   - @/hooks/useCollections → stub with empty data
 *   - @/components/* → stub heavy sub-components to simple divs
 *   - @/lib/i18n → returns key as-is for predictable text assertions
 *   - sonner → stub toast helpers
 *   - @/lib/api → stub batchUpdate
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const { mockUseInfiniteLibraryGalleries } = vi.hoisted(() => ({
  mockUseInfiniteLibraryGalleries: vi.fn(),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/hooks/useGalleries', () => ({
  useInfiniteLibraryGalleries: mockUseInfiniteLibraryGalleries,
}))

vi.mock('@/hooks/useCollections', () => ({
  useCollections: () => ({ data: undefined }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
  formatNumber: (n: number) => String(n),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/api', () => ({
  api: { library: { batchUpdate: vi.fn() } },
}))

// Stub Next.js Link so it renders a plain <a> element
vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/components/GalleryCard', () => ({
  LibraryGalleryCard: ({ gallery }: { gallery: { title: string } }) => (
    <div data-testid="gallery-card">{gallery.title}</div>
  ),
}))

vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: ({ items, renderItem }: { items: unknown[]; renderItem: (item: unknown, index: number) => React.ReactNode }) => (
    <div data-testid="virtual-grid">{items.map((item, i) => renderItem(item, i))}</div>
  ),
}))

vi.mock('@/components/Pagination', () => ({
  Pagination: ({ page, total }: { page: number; total: number }) => (
    <div data-testid="pagination" data-page={page} data-total={total} />
  ),
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}))

vi.mock('@/components/EmptyState', () => ({
  EmptyState: ({ title }: { title: string }) => <div data-testid="empty-state">{title}</div>,
}))

// ── Import page after mocks ──────────────────────────────────────────

import LibraryPage from '@/app/library/page'

// ── Factories ─────────────────────────────────────────────────────────

function makeGallery(id: number, title = `Gallery ${id}`) {
  return {
    id,
    title,
    title_jpn: '',
    category: 'manga',
    language: 'english',
    pages: 20,
    rating: 4,
    favorited: false,
    is_favorited: false,
    my_rating: null,
    uploader: 'user',
    source: 'local',
    artist_id: null,
    download_status: 'complete' as const,
    import_mode: null,
    tags_array: [],
    cover_thumb: null,
    posted_at: null,
    added_at: new Date().toISOString(),
  }
}

// ── Default hook return value ─────────────────────────────────────────

function setLoadingState() {
  mockUseInfiniteLibraryGalleries.mockReturnValue({
    galleries: [],
    total: 0,
    isLoading: true,
    error: null,
    isLoadingMore: false,
    isReachingEnd: false,
    loadMore: vi.fn(),
  })
}

function setEmptyState() {
  mockUseInfiniteLibraryGalleries.mockReturnValue({
    galleries: [],
    total: 0,
    isLoading: false,
    error: null,
    isLoadingMore: false,
    isReachingEnd: true,
    loadMore: vi.fn(),
  })
}

function setGalleriesState(galleries: ReturnType<typeof makeGallery>[], total?: number) {
  mockUseInfiniteLibraryGalleries.mockReturnValue({
    galleries,
    total: total ?? galleries.length,
    isLoading: false,
    error: null,
    isLoadingMore: false,
    isReachingEnd: false,
    loadMore: vi.fn(),
  })
}

function setErrorState(message = 'Failed to load') {
  mockUseInfiniteLibraryGalleries.mockReturnValue({
    galleries: [],
    total: 0,
    isLoading: false,
    error: new Error(message),
    isLoadingMore: false,
    isReachingEnd: false,
    loadMore: vi.fn(),
  })
}

// ── Setup / Teardown ──────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  setEmptyState()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('Library page — initial render', () => {
  it('test_library_renders_pageTitle', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.title')).toBeInTheDocument()
  })

  it('test_library_renders_searchInput', () => {
    render(<LibraryPage />)
    const input = screen.getByPlaceholderText('library.searchPlaceholder')
    expect(input).toBeInTheDocument()
  })

  it('test_library_renders_includeTags_label', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.includeTags')).toBeInTheDocument()
  })

  it('test_library_renders_excludeTags_label', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.excludeTags')).toBeInTheDocument()
  })

  it('test_library_renders_minRating_label', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.minRating')).toBeInTheDocument()
  })

  it('test_library_renders_source_label', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.source')).toBeInTheDocument()
  })

  it('test_library_renders_sort_label', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.sort')).toBeInTheDocument()
  })

  it('test_library_renders_favoritesOnly_checkbox', () => {
    render(<LibraryPage />)
    const checkbox = screen.getByRole('checkbox')
    expect(checkbox).toBeInTheDocument()
  })
})

describe('Library page — sort dropdown', () => {
  it('test_library_sortDropdown_defaultValueIsAddedAt', () => {
    render(<LibraryPage />)
    const select = screen.getByDisplayValue('library.dateAdded')
    expect(select).toBeInTheDocument()
  })

  it('test_library_sortDropdown_hasRatingOption', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.rating')).toBeInTheDocument()
  })

  it('test_library_sortDropdown_hasPagesOption', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.pagesSort')).toBeInTheDocument()
  })

  it('test_library_sortDropdown_onChange_callsHookWithNewSort', async () => {
    const user = userEvent.setup()
    render(<LibraryPage />)
    const select = screen.getByDisplayValue('library.dateAdded')
    await user.selectOptions(select, 'rating')
    // After sort change, the hook should have been called again with sort: 'rating'
    const lastCall = mockUseInfiniteLibraryGalleries.mock.calls[mockUseInfiniteLibraryGalleries.mock.calls.length - 1]
    expect(lastCall[0]).toMatchObject({ sort: 'rating' })
  })
})

describe('Library page — source dropdown', () => {
  it('test_library_sourceDropdown_hasAllSourcesOption', () => {
    render(<LibraryPage />)
    expect(screen.getByText('library.allSources')).toBeInTheDocument()
  })

  it('test_library_sourceDropdown_hasEhentaiOption', () => {
    render(<LibraryPage />)
    expect(screen.getByText('E-Hentai')).toBeInTheDocument()
  })

  it('test_library_sourceDropdown_onChange_callsHookWithSource', async () => {
    const user = userEvent.setup()
    render(<LibraryPage />)
    const select = screen.getByDisplayValue('library.allSources')
    await user.selectOptions(select, 'ehentai')
    const lastCall = mockUseInfiniteLibraryGalleries.mock.calls[mockUseInfiniteLibraryGalleries.mock.calls.length - 1]
    expect(lastCall[0]).toMatchObject({ source: 'ehentai' })
  })
})

describe('Library page — empty state', () => {
  it('test_library_emptyGalleries_rendersEmptyState', () => {
    setEmptyState()
    render(<LibraryPage />)
    expect(screen.getByTestId('empty-state')).toBeInTheDocument()
  })

  it('test_library_emptyGalleries_rendersNoGalleryCards', () => {
    setEmptyState()
    render(<LibraryPage />)
    expect(screen.queryByTestId('gallery-card')).not.toBeInTheDocument()
  })

  it('test_library_emptyGalleries_emptyStateTitleIsLibraryNoGalleries', () => {
    setEmptyState()
    render(<LibraryPage />)
    expect(screen.getByText('library.noGalleries')).toBeInTheDocument()
  })
})

describe('Library page — loading state', () => {
  it('test_library_loading_rendersSpinner', () => {
    setLoadingState()
    render(<LibraryPage />)
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
  })

  it('test_library_loading_doesNotRenderEmptyState', () => {
    setLoadingState()
    render(<LibraryPage />)
    expect(screen.queryByTestId('empty-state')).not.toBeInTheDocument()
  })
})

describe('Library page — error state', () => {
  it('test_library_error_rendersErrorMessage', () => {
    setErrorState('Something went wrong')
    render(<LibraryPage />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('test_library_error_doesNotRenderGalleryCards', () => {
    setErrorState()
    render(<LibraryPage />)
    expect(screen.queryByTestId('gallery-card')).not.toBeInTheDocument()
  })
})

describe('Library page — gallery results', () => {
  it('test_library_withGalleries_rendersGalleryCards', () => {
    setGalleriesState([makeGallery(1), makeGallery(2)])
    render(<LibraryPage />)
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(2)
  })

  it('test_library_withGalleries_galleryCardShowsTitle', () => {
    setGalleriesState([makeGallery(1, 'My Doujin')])
    render(<LibraryPage />)
    expect(screen.getByText('My Doujin')).toBeInTheDocument()
  })

  it('test_library_withGalleries_galleryCardLinksToDetailPage', () => {
    setGalleriesState([makeGallery(7)])
    render(<LibraryPage />)
    const link = screen.getByRole('link', { name: /Gallery 7/ })
    expect(link).toHaveAttribute('href', '/library/7')
  })

  it('test_library_withGalleries_showsTotalCount', () => {
    setGalleriesState([makeGallery(1)], 42)
    render(<LibraryPage />)
    expect(screen.getByText(/42/)).toBeInTheDocument()
  })
})

describe('Library page — tag filters', () => {
  it('test_library_includeTag_addingTagViaButton', async () => {
    const user = userEvent.setup()
    render(<LibraryPage />)
    const input = screen.getByPlaceholderText('library.tagFilterPlaceholder')
    await user.type(input, 'artist:cloba')
    // The add-include-tag button is the green button next to the include input.
    // It is the first button that follows the include input (green bg class).
    const addBtn = screen.getAllByRole('button').find(
      (b) => b.className.includes('bg-green-600'),
    )!
    await user.click(addBtn)
    // After adding, hook should be called with tags containing 'artist:cloba'
    const lastCall = mockUseInfiniteLibraryGalleries.mock.calls[mockUseInfiniteLibraryGalleries.mock.calls.length - 1]
    expect(lastCall[0]?.tags).toContain('artist:cloba')
  })

  it('test_library_includeTag_addingTagViaEnterKey', async () => {
    const user = userEvent.setup()
    render(<LibraryPage />)
    const input = screen.getByPlaceholderText('library.tagFilterPlaceholder')
    await user.type(input, 'character:rem{Enter}')
    const lastCall = mockUseInfiniteLibraryGalleries.mock.calls[mockUseInfiniteLibraryGalleries.mock.calls.length - 1]
    expect(lastCall[0]?.tags).toContain('character:rem')
  })

  it('test_library_excludeTag_addingTagViaEnterKey', async () => {
    const user = userEvent.setup()
    render(<LibraryPage />)
    const input = screen.getByPlaceholderText('library.excludeTagPlaceholder')
    await user.type(input, 'language:chinese{Enter}')
    const lastCall = mockUseInfiniteLibraryGalleries.mock.calls[mockUseInfiniteLibraryGalleries.mock.calls.length - 1]
    expect(lastCall[0]?.exclude_tags).toContain('language:chinese')
  })
})

describe('Library page — favorites filter', () => {
  it('test_library_favoritesCheckbox_uncheckedByDefault', () => {
    render(<LibraryPage />)
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement
    expect(checkbox.checked).toBe(false)
  })

  it('test_library_favoritesCheckbox_checked_callsHookWithFavoritedTrue', async () => {
    const user = userEvent.setup()
    render(<LibraryPage />)
    const checkbox = screen.getByRole('checkbox')
    await user.click(checkbox)
    const lastCall = mockUseInfiniteLibraryGalleries.mock.calls[mockUseInfiniteLibraryGalleries.mock.calls.length - 1]
    // favorited: true or truthy
    expect(lastCall[0]?.favorited).toBeTruthy()
  })
})
