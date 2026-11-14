import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string, params?: Record<string, string | number>) =>
    params ? `${key} ${Object.values(params).join(' ')}` : key,
}))

import { facetSelection, parseQuery, setFacet } from '@/lib/queryParser'
import {
  LibraryFilterPanel,
  type LibraryFilterSection,
} from '@/components/library/LibraryFilterPanel'

type Props = React.ComponentProps<typeof LibraryFilterPanel>

function baseProps(): Props {
  return {
    section: null,
    onSectionChange: vi.fn(),
    categoryOptions: [
      { value: 'Cosplay', label: 'Cosplay', count: 12, colorKey: 'Cosplay' },
      { value: 'Manga', label: 'Manga', count: 3, colorKey: 'Manga' },
    ],
    sourceOptions: [
      { value: 'pixiv', label: 'Pixiv', count: 5 },
      { value: 'local:link', label: 'External Folders', count: 9 },
    ],
    categorySelection: { mode: 'include', values: [] },
    sourceSelection: { mode: 'include', values: [] },
    onFacetChange: vi.fn(),
    rating: null,
    onRatingChange: vi.fn(),
    collection: null,
    collections: [{ value: 7, label: 'Best (3)' }],
    onCollectionChange: vi.fn(),
    sort: 'added_at',
    sortOptions: [
      { value: 'added_at', label: 'Added' },
      { value: 'rating', label: 'Rating' },
    ],
    onSortChange: vi.fn(),
    onReset: vi.fn(),
    hasActiveFilters: false,
  }
}

function setup(overrides: Partial<Props> = {}) {
  const props = { ...baseProps(), ...overrides }
  render(<LibraryFilterPanel {...props} />)
  return props
}

const pill = (section: LibraryFilterSection) =>
  document.querySelector(`button[data-section="${section}"]`) as HTMLElement
const openSection = () => screen.getByTestId('library-filter-section')

describe('LibraryFilterPanel', () => {
  it('filter_panel_shows_only_the_pill_row_until_a_pill_is_tapped', () => {
    const props = setup()
    expect(screen.queryByTestId('library-filter-section')).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(pill('category')).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(pill('category'))
    expect(props.onSectionChange).toHaveBeenCalledWith('category')
  })

  it('filter_panel_tapping_the_open_pill_collapses_its_section', () => {
    const props = setup({ section: 'source' })
    expect(pill('source')).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(pill('source'))
    expect(props.onSectionChange).toHaveBeenCalledWith(null)
  })

  it('filter_panel_pills_show_the_current_value_of_each_filter', () => {
    setup({
      categorySelection: { mode: 'include', values: ['Manga', 'Cosplay'] },
      sourceSelection: { mode: 'exclude', values: ['local:link'] },
      rating: 4,
      collection: 7,
      sort: 'rating',
    })
    expect(pill('category')).toHaveTextContent('library.facetMore Manga 1')
    expect(pill('source')).toHaveTextContent('library.facetNot External Folders')
    expect(pill('rating')).toHaveTextContent('library.rating 4+')
    expect(pill('collection')).toHaveTextContent('Best (3)')
    expect(pill('sort')).toHaveTextContent('library.sort · Rating')
  })

  it('filter_panel_hides_the_collection_pill_without_collections', () => {
    setup({ collections: [] })
    expect(pill('collection')).toBeNull()
  })

  it('filter_panel_category_chip_toggles_include_selection_and_keeps_the_section_open', () => {
    const props = setup({
      section: 'category',
      categorySelection: { mode: 'include', values: ['Manga'] },
    })
    const chip = within(openSection()).getByRole('button', { name: /Cosplay/ })
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(chip)
    expect(props.onFacetChange).toHaveBeenCalledWith('category', {
      mode: 'include',
      values: ['Manga', 'Cosplay'],
    })
    expect(props.onSectionChange).not.toHaveBeenCalled()
  })

  it('filter_panel_category_exclude_mode_persists_before_first_chip', () => {
    const onFacetChange = vi.fn()
    function Harness() {
      const [q, setQ] = useState('')
      return (
        <LibraryFilterPanel
          {...baseProps()}
          section="category"
          categorySelection={facetSelection(parseQuery(q), 'category')}
          onFacetChange={(key, sel) => {
            onFacetChange(key, sel)
            setQ(setFacet(q, key, sel))
          }}
        />
      )
    }
    render(<Harness />)

    fireEvent.click(screen.getByRole('radio', { name: 'library.facetExcept' }))
    expect(screen.getByRole('radio', { name: 'library.facetExcept' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    fireEvent.click(within(openSection()).getByRole('button', { name: /Cosplay/ }))
    expect(onFacetChange).toHaveBeenLastCalledWith('category', {
      mode: 'exclude',
      values: ['Cosplay'],
    })
  })

  it('filter_panel_source_section_lists_checkboxes_that_extend_the_selection', () => {
    const props = setup({
      section: 'source',
      sourceSelection: { mode: 'exclude', values: ['local:link'] },
    })
    fireEvent.click(within(openSection()).getByRole('checkbox', { name: /Pixiv/ }))
    expect(props.onFacetChange).toHaveBeenCalledWith('source', {
      mode: 'exclude',
      values: ['local:link', 'pixiv'],
    })
  })

  it('filter_panel_rating_pick_applies_and_collapses', () => {
    const props = setup({ section: 'rating' })
    fireEvent.click(within(openSection()).getByRole('radio', { name: '3+' }))
    expect(props.onRatingChange).toHaveBeenCalledWith('3')
    expect(props.onSectionChange).toHaveBeenCalledWith(null)
  })

  it('filter_panel_rating_any_clears_the_rating', () => {
    const props = setup({ section: 'rating', rating: 3 })
    fireEvent.click(within(openSection()).getByRole('radio', { name: 'library.any' }))
    expect(props.onRatingChange).toHaveBeenCalledWith(null)
  })

  it('filter_panel_default_sort_pick_clears_the_sort_token', () => {
    const props = setup({ section: 'sort', sort: 'rating' })
    fireEvent.click(within(openSection()).getByRole('radio', { name: 'Added' }))
    expect(props.onSortChange).toHaveBeenCalledWith(null)
    expect(props.onSectionChange).toHaveBeenCalledWith(null)
  })

  it('filter_panel_collection_pick_sends_the_id_and_all_clears_it', () => {
    const props = setup({ section: 'collection', collection: null })
    fireEvent.click(within(openSection()).getByRole('radio', { name: 'Best (3)' }))
    expect(props.onCollectionChange).toHaveBeenCalledWith('7')
    fireEvent.click(
      within(openSection()).getByRole('radio', { name: 'collections.allCollections' }),
    )
    expect(props.onCollectionChange).toHaveBeenLastCalledWith(null)
  })

  it('filter_panel_reset_pill_only_with_active_filters_and_keeps_typed_text', () => {
    // Delegates to the page's clearFilters, which keeps the free text.
    const { unmount } = render(<LibraryFilterPanel {...baseProps()} />)
    expect(screen.queryByRole('button', { name: 'library.resetFilters' })).toBeNull()
    unmount()

    const props = setup({ hasActiveFilters: true })
    fireEvent.click(screen.getByRole('button', { name: 'library.resetFilters' }))
    expect(props.onReset).toHaveBeenCalledTimes(1)
    expect(props.onFacetChange).not.toHaveBeenCalled()
  })

  it('filter_panel_help_section_shows_the_syntax_cheat_sheet', () => {
    setup({ section: 'help' })
    expect(within(openSection()).getByText(/library\.syntaxTagSearch/)).toBeInTheDocument()
  })

  it('filter_panel_pointer_press_on_a_pill_does_not_take_focus', () => {
    // Focus inside the search block pins it; a pill tap must leave it free to hide.
    setup()
    expect(fireEvent.mouseDown(pill('rating'))).toBe(false)
  })
})
