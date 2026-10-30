/**
 * Library header + one-row search/filter bar.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
  selectMode: false,
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
    selectMode: search.selectMode,
    setSelectMode: search.setSelectMode,
    selectedIds: new Set<number>(),
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

const PLACEHOLDER = 'library.searchPlaceholder'
const removeButtons = () => screen.queryAllByRole('button', { name: /^library\.removeFilter/ })

beforeEach(() => {
  vi.clearAllMocks()
  search.inputValue = ''
  search.parsed = { ...emptyParsed }
  search.selectMode = false
  search.total = 0
})

describe('Library header', () => {
  it('test_header_holds_view_toggle_and_select_button', () => {
    search.total = 1234
    render(<LibraryPage />)

    const heading = screen.getByRole('heading', { name: 'library.title' })
    const header = heading.parentElement?.parentElement as HTMLElement
    expect(header).toBeTruthy()
    expect(within(header).getByTitle('browse.gridView')).toBeInTheDocument()
    expect(within(header).getByTitle('browse.listView')).toBeInTheDocument()
    const select = within(header).getByRole('button', { name: 'library.select' })
    expect(select).toHaveAttribute('aria-pressed', 'false')
    expect(header).toHaveTextContent('library.galleries')

    fireEvent.click(select)
    expect(search.setSelectMode).toHaveBeenCalled()
  })

  it('test_select_button_reflects_pressed_state_when_select_mode_is_on', () => {
    search.selectMode = true
    render(<LibraryPage />)

    expect(screen.getByRole('button', { name: 'library.select' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})

describe('Library filter chips', () => {
  it('test_no_chip_row_without_active_filters', () => {
    render(<LibraryPage />)

    expect(removeButtons()).toHaveLength(0)
    expect(screen.queryByText('library.clearAllFilters')).toBeNull()
    expect(screen.getByRole('button', { name: 'library.filters' })).toBeInTheDocument()
  })

  it('test_filter_badge_counts_active_filters', () => {
    search.parsed = { ...emptyParsed, source: 'pixiv', rating: 4, favorited: true }
    render(<LibraryPage />)

    const button = screen.getByRole('button', { name: 'library.filters' })
    expect(within(button).getByText('3')).toBeInTheDocument()
    expect(removeButtons()).toHaveLength(3)
  })

  it('test_filter_badge_absent_without_active_filters', () => {
    render(<LibraryPage />)

    const button = screen.getByRole('button', { name: 'library.filters' })
    expect(button).toHaveTextContent('')
  })

  it('test_chip_remove_clears_only_that_filter', () => {
    search.parsed = { ...emptyParsed, source: 'local', importMode: 'link', rating: 4 }
    render(<LibraryPage />)
    expect(removeButtons()).toHaveLength(2) // source+import pair is one chip

    const sourceRemove = removeButtons()[0] // source precedes rating in chip order
    fireEvent.click(sourceRemove)

    expect(search.setFilter).toHaveBeenCalledTimes(2)
    expect(search.setFilter).toHaveBeenCalledWith('source', null)
    expect(search.setFilter).toHaveBeenCalledWith('import', null)
    expect(search.setFilter).not.toHaveBeenCalledWith('rating', null)
    expect(search.clearFilters).not.toHaveBeenCalled()
  })

  it('test_favorited_chip_remove_clears_only_favorited', () => {
    search.parsed = { ...emptyParsed, favorited: true }
    render(<LibraryPage />)

    fireEvent.click(removeButtons()[0])

    expect(search.setFilter).toHaveBeenCalledTimes(1)
    expect(search.setFilter).toHaveBeenCalledWith('favorited', null)
  })

  it('test_clear_all_hidden_with_single_chip_and_shown_with_two', () => {
    search.parsed = { ...emptyParsed, favorited: true }
    const view = render(<LibraryPage />)
    expect(screen.queryByText('library.clearAllFilters')).toBeNull()
    view.unmount()

    search.parsed = { ...emptyParsed, favorited: true, readingList: true }
    render(<LibraryPage />)
    fireEvent.click(screen.getByText('library.clearAllFilters'))
    expect(search.clearFilters).toHaveBeenCalledTimes(1)
  })
})

describe('Library search focus behaviour', () => {
  it('test_focus_hides_filter_button_and_shows_cancel', () => {
    render(<LibraryPage />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    const filterButton = () => screen.getByRole('button', { name: 'library.filters', hidden: true })

    expect(filterButton().closest('[aria-hidden="true"]')).toBeNull()
    expect(screen.queryByRole('button', { name: 'common.cancel' })).toBeNull()

    fireEvent.focus(input)

    expect(filterButton().closest('[aria-hidden="true"]')).not.toBeNull()
    expect(filterButton()).toHaveAttribute('tabindex', '-1')
    expect(screen.getByRole('button', { name: 'common.cancel' })).toBeInTheDocument()
  })

  it('test_cancel_clears_text', () => {
    search.inputValue = 'rem'
    render(<LibraryPage />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    act(() => input.focus())
    expect(document.activeElement).toBe(input)

    const cancel = screen.getByRole('button', { name: 'common.cancel' })
    fireEvent.click(cancel)

    expect(search.clearSearch).toHaveBeenCalledTimes(1)
    expect(document.activeElement).not.toBe(input)
  })

  it('test_enter_commits_and_blurs', () => {
    search.inputValue = 'rem source:pixiv'
    render(<LibraryPage />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    act(() => input.focus())

    fireEvent.keyDown(input, { key: 'Enter' })

    expect(search.commitSearch).toHaveBeenCalledWith('rem source:pixiv')
    expect(document.activeElement).not.toBe(input)
  })

  it('test_typing_calls_handle_input_change_with_text', () => {
    render(<LibraryPage />)
    fireEvent.change(screen.getByPlaceholderText(PLACEHOLDER), { target: { value: 'ram' } })

    expect(search.handleInputChange).toHaveBeenCalledWith('ram')
  })
})

describe('Library filter panel', () => {
  it('test_filter_button_expands_the_inline_panel_instead_of_opening_a_dialog', () => {
    const { container } = render(<LibraryPage />)
    const button = screen.getByRole('button', { name: 'library.filters' })
    const panel = container.querySelector('#library-filter-panel')

    expect(panel).not.toBeNull()
    expect(button).toHaveAttribute('aria-controls', 'library-filter-panel')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    // Collapsed: the controls stay in the DOM but out of the tab order.
    expect(panel).toHaveAttribute('inert')

    fireEvent.click(button)

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(panel).not.toHaveAttribute('inert')
    expect(panel?.querySelectorAll('select').length).toBeGreaterThan(0)

    fireEvent.click(button)

    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(panel).toHaveAttribute('inert')
  })

  it('test_syntax_help_stays_hidden_until_its_toggle_in_the_panel_is_pressed', () => {
    render(<LibraryPage />)
    fireEvent.click(screen.getByRole('button', { name: 'library.filters' }))
    expect(screen.queryByText(/library\.syntaxTagSearch/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /library\.syntaxHelp/ }))

    expect(screen.getByText(/library\.syntaxTagSearch/)).toBeInTheDocument()
  })
})

describe('Library search block scroll reveal', () => {
  it('test_search_block_is_sticky_below_the_status_bar_and_holds_search_panel_and_chips', () => {
    const { container } = render(<LibraryPage />)
    const block = screen.getByTestId('library-search-block')

    expect(block.className).toMatch(/(^|\s)sticky(\s|$)/)
    expect(block.style.top).toBe('var(--sat)')
    expect(block).toContainElement(screen.getByPlaceholderText(PLACEHOLDER))
    expect(block).toContainElement(container.querySelector('#library-filter-panel') as HTMLElement)
    // At the top of the page nothing is slid away.
    expect(block).not.toHaveAttribute('data-scroll-hidden')
    expect(block.style.transform).toBe('')
  })
})
