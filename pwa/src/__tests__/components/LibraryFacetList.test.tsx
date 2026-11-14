import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string, params?: Record<string, string | number>) =>
    params ? `${key} ${Object.values(params).join(' ')}` : key,
}))

import {
  LibraryFacetList,
  facetGridColumns,
  type FacetOption,
} from '@/components/library/LibraryFacetList'
import { facetSelection, parseQuery, setFacet, type FacetSelection } from '@/lib/queryParser'
import { LibraryFacetButton } from '@/components/library/LibraryFacetButton'

const options: FacetOption[] = [
  { value: 'Cosplay', label: 'Cosplay', count: 12, colorKey: 'Cosplay' },
  { value: 'Manga', label: 'Manga', count: 3, colorKey: 'Manga' },
  { value: 'Empty', label: 'Empty', count: 0, colorKey: 'Empty' },
]

describe('LibraryFacetList', () => {
  it('facet_list_switching_mode_keeps_checked_values', () => {
    const onChange = vi.fn()
    render(
      <LibraryFacetList
        options={options}
        selection={{ mode: 'include', values: ['Cosplay', 'Manga'] }}
        onChange={onChange}
      />,
    )

    fireEvent.click(screen.getByRole('radio', { name: 'library.facetExcept' }))

    expect(onChange).toHaveBeenCalledWith({ mode: 'exclude', values: ['Cosplay', 'Manga'] })
    expect(screen.getByRole('radio', { name: 'library.facetOnly' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })

  it('facet_list_hides_zero_count_option_unless_selected', () => {
    const { rerender } = render(
      <LibraryFacetList
        options={options}
        selection={{ mode: 'include', values: [] }}
        onChange={vi.fn()}
      />,
    )
    expect(screen.queryByRole('checkbox', { name: /Empty/ })).toBeNull()
    expect(screen.getByRole('checkbox', { name: /Cosplay/ })).toBeInTheDocument()

    rerender(
      <LibraryFacetList
        options={options}
        selection={{ mode: 'include', values: ['Empty'] }}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByRole('checkbox', { name: /Empty/ })).toBeChecked()
  })

  it('facet_list_toggling_a_checkbox_adds_and_removes_the_value_in_current_mode', () => {
    const onChange = vi.fn()
    render(
      <LibraryFacetList
        options={options}
        selection={{ mode: 'exclude', values: ['Manga'] }}
        onChange={onChange}
      />,
    )

    fireEvent.click(screen.getByRole('checkbox', { name: /Cosplay/ }))
    expect(onChange).toHaveBeenLastCalledWith({ mode: 'exclude', values: ['Manga', 'Cosplay'] })

    fireEvent.click(screen.getByRole('checkbox', { name: /Manga/ }))
    expect(onChange).toHaveBeenLastCalledWith({ mode: 'exclude', values: [] })
  })

  it('facet_list_shows_category_swatch_only_for_options_with_a_color_key', () => {
    render(
      <LibraryFacetList
        options={[...options, { value: 'pixiv', label: 'Pixiv', count: 2 }]}
        selection={{ mode: 'include', values: [] }}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getAllByTestId('facet-swatch')).toHaveLength(2)
  })

  it('facet_list_filter_input_appears_only_above_eight_options', () => {
    const many = Array.from({ length: 9 }, (_, i) => ({
      value: `c${i}`,
      label: `Cat ${i}`,
      count: 1,
    }))
    const selection = { mode: 'include' as const, values: [] }
    const { rerender } = render(
      <LibraryFacetList options={many.slice(0, 8)} selection={selection} onChange={vi.fn()} />,
    )
    expect(screen.queryByPlaceholderText('library.facetFilterPlaceholder')).toBeNull()

    rerender(<LibraryFacetList options={many} selection={selection} onChange={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('library.facetFilterPlaceholder'), {
      target: { value: 'cat 7' },
    })
    expect(screen.getAllByRole('checkbox')).toHaveLength(1)
  })
})

describe('LibraryFacetButton label', () => {
  const label = (selection: { mode: 'include' | 'exclude'; values: string[] }) => {
    render(
      <LibraryFacetButton
        label="Category"
        options={options}
        selection={selection}
        onChange={vi.fn()}
      />,
    )
    return screen.getByRole('button')
  }

  it('facet_button_label_shows_facet_name_when_nothing_selected', () => {
    expect(label({ mode: 'include', values: [] })).toHaveTextContent('Category')
  })

  it('facet_button_label_shows_first_value_plus_count_in_include_mode', () => {
    expect(label({ mode: 'include', values: ['Cosplay', 'Manga'] })).toHaveTextContent(
      'library.facetMore Cosplay 1',
    )
  })

  it('facet_button_label_shows_not_prefix_in_exclude_mode', () => {
    const button = label({ mode: 'exclude', values: ['Manga'] })
    expect(button).toHaveTextContent('library.facetNot Manga')
    expect(button.className).toContain('border-vault-accent')
  })
})

describe('LibraryFacetButton popover', () => {
  it('facet_button_opens_popover_lazily_and_reports_open_state', async () => {
    const onOpenChange = vi.fn()
    render(
      <LibraryFacetButton
        label="Category"
        options={options}
        selection={{ mode: 'include', values: [] }}
        onChange={vi.fn()}
        onOpenChange={onOpenChange}
      />,
    )
    expect(screen.queryByRole('dialog')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Category' }))

    expect(await screen.findByRole('dialog', { name: 'Category' })).toBeInTheDocument()
    expect(onOpenChange).toHaveBeenLastCalledWith(true)
  })
})

describe('LibraryFacetList mode draft', () => {
  it('facet_list_exclude_mode_persists_before_first_check', () => {
    const onChange = vi.fn()
    // Round-trips through the query like the page does: an empty facet records no mode.
    function Harness() {
      const [q, setQ] = useState('')
      const selection = facetSelection(parseQuery(q), 'source')
      return (
        <LibraryFacetList
          options={options}
          selection={selection}
          onChange={(next: FacetSelection) => {
            onChange(next)
            setQ(setFacet(q, 'source', next))
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
    fireEvent.click(screen.getByRole('checkbox', { name: /Cosplay/ }))

    expect(onChange).toHaveBeenLastCalledWith({ mode: 'exclude', values: ['Cosplay'] })
    expect(screen.getByRole('radio', { name: 'library.facetExcept' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })
})

const manyOptions = (n: number): FacetOption[] =>
  Array.from({ length: n }, (_, i) => ({ value: `src${i}`, label: `src${i}`, count: n - i }))

describe('Desktop facet grid', () => {
  it('facet_grid_columns_widen_before_the_list_gets_tall', () => {
    expect(facetGridColumns(6)).toBe(1)
    expect(facetGridColumns(7)).toBe(2)
    expect(facetGridColumns(11)).toBe(2)
    expect(facetGridColumns(20)).toBe(2)
    expect(facetGridColumns(21)).toBe(3)
  })

  it('facet_popover_with_eleven_sources_shows_two_columns_and_no_filter_input', async () => {
    render(
      <LibraryFacetButton
        label="Source"
        options={manyOptions(11)}
        selection={{ mode: 'include', values: [] }}
        onChange={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Source' }))
    const dialog = await screen.findByRole('dialog', { name: 'Source' })

    expect(screen.getByTestId('facet-options')).toHaveAttribute('data-columns', '2')
    expect(screen.getAllByRole('checkbox')).toHaveLength(11)
    // Every option is on screen at once, so the grid has no filter box at this size.
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(dialog.className).toContain('w-[30rem]')
  })

  it('facet_grid_keeps_filter_input_once_options_outgrow_the_grid', () => {
    render(
      <LibraryFacetList
        options={manyOptions(25)}
        selection={{ mode: 'include', values: [] }}
        onChange={vi.fn()}
        columns={3}
      />,
    )
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('facet_list_without_columns_keeps_single_column_and_early_filter_for_the_sheet', () => {
    render(
      <LibraryFacetList
        options={manyOptions(11)}
        selection={{ mode: 'include', values: [] }}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByTestId('facet-options')).toHaveAttribute('data-columns', '1')
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })
})
