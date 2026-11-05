import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string, params?: Record<string, string | number>) =>
    params ? `${key} ${Object.values(params).join(' ')}` : key,
}))

import { facetSelection, parseQuery, setFacet } from '@/lib/queryParser'
import { LibraryFilterSheet } from '@/components/library/LibraryFilterSheet'

function baseProps(): React.ComponentProps<typeof LibraryFilterSheet> {
  return {
    open: true,
    onOpenChange: vi.fn(),
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
    collections: [],
    onCollectionChange: vi.fn(),
    sort: 'added_at',
    sortOptions: [{ value: 'added_at', label: 'Added' }],
    onSortChange: vi.fn(),
    onReset: vi.fn(),
    total: 42,
  }
}

function setup(overrides: Partial<React.ComponentProps<typeof LibraryFilterSheet>> = {}) {
  const props = { ...baseProps(), ...overrides }
  render(<LibraryFilterSheet {...props} />)
  return props
}

describe('LibraryFilterSheet', () => {
  it('filter_sheet_reset_keeps_typed_text', () => {
    // The sheet delegates to the page's clearFilters (= withoutFilters), which
    // keeps the free text; it must not clear the search itself.
    const props = setup()
    fireEvent.click(screen.getByRole('button', { name: 'library.resetFilters' }))
    expect(props.onReset).toHaveBeenCalledTimes(1)
    expect(props.onFacetChange).not.toHaveBeenCalled()
    expect(props.onOpenChange).not.toHaveBeenCalled()
  })

  it('filter_sheet_footer_shows_count_and_closes_the_sheet', () => {
    const props = setup()
    fireEvent.click(screen.getByRole('button', { name: 'library.showResults 42' }))
    expect(props.onOpenChange).toHaveBeenCalledWith(false)
  })

  it('filter_sheet_footer_says_done_when_total_unknown', () => {
    setup({ total: null })
    expect(screen.getByRole('button', { name: 'common.done' })).toBeInTheDocument()
  })

  it('filter_sheet_category_chip_toggles_include_selection', () => {
    const props = setup({ categorySelection: { mode: 'include', values: ['Manga'] } })
    const chip = screen.getByRole('button', { name: /Cosplay/ })
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(chip)
    expect(props.onFacetChange).toHaveBeenCalledWith('category', {
      mode: 'include',
      values: ['Manga', 'Cosplay'],
    })
  })

  it('filter_sheet_source_row_expands_inline_list_and_summarises_selection', () => {
    const props = setup({ sourceSelection: { mode: 'exclude', values: ['local:link'] } })
    const row = screen.getByRole('button', { name: /library\.facetNot External Folders/ })
    expect(screen.queryByRole('checkbox')).toBeNull()

    fireEvent.click(row)
    const dialog = screen.getByRole('dialog')
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Pixiv/ }))

    expect(props.onFacetChange).toHaveBeenCalledWith('source', {
      mode: 'exclude',
      values: ['local:link', 'pixiv'],
    })
  })

  it('filter_sheet_category_exclude_mode_persists_before_first_chip', () => {
    const onFacetChange = vi.fn()
    function Harness() {
      const [q, setQ] = useState('')
      return (
        <LibraryFilterSheet
          {...baseProps()}
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
    fireEvent.click(screen.getByRole('button', { name: /Cosplay/ }))
    expect(onFacetChange).toHaveBeenLastCalledWith('category', {
      mode: 'exclude',
      values: ['Cosplay'],
    })
  })

  it('filter_sheet_has_syntax_help_toggle', () => {
    setup()
    expect(screen.queryByText(/library\.syntaxTagSearch/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /library\.syntaxHelp/ }))
    expect(screen.getByText(/library\.syntaxTagSearch/)).toBeInTheDocument()
  })
})
