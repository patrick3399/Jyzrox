/**
 * Library search bar — one-tap clear, and always reachable.
 *
 * Clearing a search used to mean selecting and deleting the text by hand. The
 * bar now carries its own clear button whenever it holds a query.
 *
 * The bar also used to live inside the collapsible filter panel, which starts
 * collapsed on mobile, so searching took an extra tap to open the panel first.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const search = vi.hoisted(() => ({ inputValue: '', clearSearch: vi.fn(), clearFilters: vi.fn() }))

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string) => key,
}))
vi.mock('@/hooks/useUnifiedSearch', () => ({
  useUnifiedSearch: () => ({
    rawQuery: search.inputValue,
    inputValue: search.inputValue,
    parsed: {
      tags: [],
      nameOnlyTags: [],
      excludeTags: [],
      title: null,
      source: null,
      rating: null,
      favorited: false,
      readingList: false,
      collection: null,
      artistId: null,
      category: null,
      importMode: null,
      sort: null,
    },
    setFilter: vi.fn(),
    commitSearch: vi.fn(),
    clearSearch: search.clearSearch,
    clearFilters: search.clearFilters,
    handleInputChange: vi.fn(),
    selectMode: false,
    setSelectMode: vi.fn(),
    selectedIds: new Set<number>(),
    setSelectedIds: vi.fn(),
  }),
}))
vi.mock('@/hooks/useLibraryBrowseSession', () => ({
  useLibraryBrowseSession: () => ({
    state: {
      identityKey: 'library:A',
      items: [],
      total: 0,
      status: 'idle',
      error: null,
      hasMore: false,
    },
    loadMore: vi.fn(),
    refresh: vi.fn(),
    retry: vi.fn(),
    checkpoint: vi.fn(),
    updateView: vi.fn(),
    restoreInstruction: null,
    acknowledgeRestore: vi.fn(),
  }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'member', role: 'member' } }),
}))
vi.mock('@/hooks/useGalleries', () => ({
  useGalleryCategories: () => ({ data: { categories: [] } }),
  useLibrarySources: () => ({ data: [] }),
}))
vi.mock('@/hooks/useCollections', () => ({
  useCollections: () => ({ data: { collections: [] } }),
}))
vi.mock('@/hooks/useDatasets', () => ({
  useDatasets: () => ({ data: { datasets: [] } }),
  useAddDatasetMembers: () => ({ trigger: vi.fn() }),
}))
vi.mock('@/hooks/useDisplayPreferences', () => ({
  useDisplayPreferences: () => ({ gallery_grid_density: 'comfortable', gallery_grid_columns: 4 }),
}))
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => null }))
vi.mock('@/components/GalleryCard', () => ({ LibraryGalleryCard: () => null }))
vi.mock('@/components/GalleryListCard', () => ({ GalleryListCard: () => null }))
vi.mock('@/lib/api', () => ({ api: { library: {} } }))

import LibraryPage from '@/app/library/page'

describe('Library search clear button', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    search.inputValue = ''
  })

  it('clears the search in one tap when the bar holds a query', () => {
    search.inputValue = 'artist_id:ehentai:someone'
    render(<LibraryPage />)

    fireEvent.click(screen.getByRole('button', { name: 'browse.clearSearch' }))

    expect(search.clearSearch).toHaveBeenCalledTimes(1)
  })

  it('offers no clear button while the bar is empty', () => {
    render(<LibraryPage />)

    expect(screen.queryByRole('button', { name: 'browse.clearSearch' })).toBeNull()
  })
})

describe('Library search bar placement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    search.inputValue = ''
  })

  it('keeps the search bar visible without any collapsible filter panel toggle', () => {
    render(<LibraryPage />)

    expect(screen.getByPlaceholderText('library.searchPlaceholder')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'library.showFilters' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'library.hideFilters' })).toBeNull()
  })

  it('puts the filter button in the same row as the search input', () => {
    render(<LibraryPage />)

    const row = screen.getByPlaceholderText('library.searchPlaceholder').closest('.flex.items-center')
    expect(row).not.toBeNull()
    expect(row).toContainElement(screen.getByRole('button', { name: 'library.filters' }))
  })
})
