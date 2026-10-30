/**
 * Library batch-tag dialog: Escape closes it and the key never reaches window (FE-T25).
 * Harness mirrors library-search-filter-row.test.tsx, with select mode on and one
 * gallery selected so the real "batch add tags" button is rendered.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

const emptyParsed = {
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
} as Record<string, unknown>

const search = vi.hoisted(() => ({
  inputValue: '',
  parsed: {} as Record<string, unknown>,
  setFilter: vi.fn(),
  clearSearch: vi.fn(),
  clearFilters: vi.fn(),
  commitSearch: vi.fn(),
  handleInputChange: vi.fn(),
  setSelectMode: vi.fn(),
  total: 0,
}))

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string, params?: Record<string, string | number>) =>
    params ? `${key} ${Object.values(params).join(' ')}` : key,
}))
vi.mock('@/hooks/useUnifiedSearch', () => ({
  useUnifiedSearch: () => ({
    rawQuery: search.inputValue,
    inputValue: search.inputValue,
    parsed: search.parsed,
    setFilter: search.setFilter,
    commitSearch: search.commitSearch,
    clearSearch: search.clearSearch,
    clearFilters: search.clearFilters,
    handleInputChange: search.handleInputChange,
    selectMode: true,
    setSelectMode: search.setSelectMode,
    selectedIds: new Set<number>([1]),
    setSelectedIds: vi.fn(),
  }),
}))
vi.mock('@/hooks/useLibraryBrowseSession', () => ({
  useLibraryBrowseSession: () => ({
    state: {
      identityKey: 'library:A',
      items: [],
      total: search.total,
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

let windowListener: Mock<(e: KeyboardEvent) => void>

beforeEach(() => {
  vi.clearAllMocks()
  search.inputValue = ''
  search.parsed = { ...emptyParsed }
  search.total = 0
  windowListener = vi.fn<(e: KeyboardEvent) => void>()
})

afterEach(() => {
  window.removeEventListener('keydown', windowListener)
})

describe('Library batch tag dialog', () => {
  it('test_batch_tag_dialog_escape_closes_with_default_prevented_and_skips_window_listener', async () => {
    render(<LibraryPage />)
    fireEvent.click(screen.getByRole('button', { name: 'library.batchAddTags' }))
    const input = screen.getByPlaceholderText('library.batchTagsPlaceholder')
    expect(input).toBeInTheDocument()

    window.addEventListener('keydown', windowListener)
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    act(() => {
      ;(document.activeElement ?? document.body).dispatchEvent(event)
    })

    await waitFor(() =>
      expect(screen.queryByPlaceholderText('library.batchTagsPlaceholder')).toBeNull(),
    )
    expect(event.defaultPrevented).toBe(true)
    expect(windowListener).not.toHaveBeenCalled()
  })
})
