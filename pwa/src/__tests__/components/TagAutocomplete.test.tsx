/**
 * TagAutocomplete — Vitest test suite
 *
 * Covers:
 *   - Renders input with placeholder
 *   - No suggestions shown initially
 *   - Fetches and displays suggestions after debounce
 *   - Selecting a suggestion calls onSelect with namespace:name
 *   - clearOnSelect=true clears input after selection
 *   - clearOnSelect=false keeps tag in input after selection
 *   - Keyboard ArrowDown/Up navigates suggestions
 *   - Pressing Enter on highlighted suggestion calls onSelect
 *   - Pressing Escape closes dropdown
 *   - Empty query shows no suggestions
 *   - API error shows no suggestions
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import type { TagItem } from '@/lib/types'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const { mockAutoComplete } = vi.hoisted(() => ({
  mockAutoComplete: vi.fn(),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/lib/api', () => ({
  api: {
    tags: {
      autocomplete: mockAutoComplete,
    },
  },
}))

// ── Import component after mocks ───────────────────────────────────────

import { TagAutocomplete } from '@/components/TagAutocomplete'

// ── Helpers ────────────────────────────────────────────────────────────

function makeTag(overrides: Partial<TagItem> = {}): TagItem {
  return {
    id: 1,
    namespace: 'artist',
    name: 'testname',
    count: 10,
    ...overrides,
  }
}

// Advance fake timer by debounce amount and flush all microtasks
async function flushDebounce() {
  await act(async () => {
    vi.advanceTimersByTime(350)
    await Promise.resolve()
  })
}

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  mockAutoComplete.mockResolvedValue([])
})

afterEach(() => {
  vi.useRealTimers()
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('TagAutocomplete', () => {
  describe('initial rendering', () => {
    it('test_tagAutocomplete_rendersInput', () => {
      render(<TagAutocomplete onSelect={vi.fn()} />)
      expect(screen.getByRole('textbox')).toBeInTheDocument()
    })

    it('test_tagAutocomplete_rendersWithDefaultPlaceholder', () => {
      render(<TagAutocomplete onSelect={vi.fn()} />)
      expect(screen.getByPlaceholderText('tag.autocomplete.placeholder')).toBeInTheDocument()
    })

    it('test_tagAutocomplete_rendersWithCustomPlaceholder', () => {
      render(<TagAutocomplete onSelect={vi.fn()} placeholder="Search tags..." />)
      expect(screen.getByPlaceholderText('Search tags...')).toBeInTheDocument()
    })

    it('test_tagAutocomplete_noSuggestionsShownInitially', () => {
      render(<TagAutocomplete onSelect={vi.fn()} />)
      expect(screen.queryByRole('list')).not.toBeInTheDocument()
    })
  })

  describe('suggestions display', () => {
    it('test_tagAutocomplete_withQuery_fetchesAfterDebounce', async () => {
      const suggestions = [makeTag({ namespace: 'artist', name: 'foo' })]
      mockAutoComplete.mockResolvedValue(suggestions)

      render(<TagAutocomplete onSelect={vi.fn()} />)
      const input = screen.getByRole('textbox')

      fireEvent.change(input, { target: { value: 'fo' } })

      // Before debounce, API not called yet
      expect(mockAutoComplete).not.toHaveBeenCalled()

      await flushDebounce()

      expect(mockAutoComplete).toHaveBeenCalledWith('fo', 10)
    })

    it('test_tagAutocomplete_withSuggestions_rendersSuggestionList', async () => {
      const suggestions = [
        makeTag({ namespace: 'artist', name: 'foo' }),
        makeTag({ id: 2, namespace: 'character', name: 'bar' }),
      ]
      mockAutoComplete.mockResolvedValue(suggestions)

      render(<TagAutocomplete onSelect={vi.fn()} />)
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: 'fo' } })

      await flushDebounce()

      expect(screen.getByRole('list')).toBeInTheDocument()
      expect(screen.getByText('foo')).toBeInTheDocument()
      expect(screen.getByText('bar')).toBeInTheDocument()
    })

    it('test_tagAutocomplete_withSuggestions_rendersNamespacePrefix', async () => {
      mockAutoComplete.mockResolvedValue([makeTag({ namespace: 'artist', name: 'foo' })])

      render(<TagAutocomplete onSelect={vi.fn()} />)
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'fo' } })

      await flushDebounce()

      expect(screen.getByText('artist:')).toBeInTheDocument()
    })

    it('test_tagAutocomplete_apiError_showsNoSuggestions', async () => {
      mockAutoComplete.mockRejectedValue(new Error('Network error'))

      render(<TagAutocomplete onSelect={vi.fn()} />)
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'err' } })

      await flushDebounce()

      expect(screen.queryByRole('list')).not.toBeInTheDocument()
    })
  })

  describe('suggestion selection', () => {
    async function renderWithSuggestions(
      props: Partial<React.ComponentProps<typeof TagAutocomplete>> = {},
    ) {
      const suggestions = [
        makeTag({ namespace: 'artist', name: 'foo' }),
        makeTag({ id: 2, namespace: 'character', name: 'bar' }),
      ]
      mockAutoComplete.mockResolvedValue(suggestions)

      const onSelect = vi.fn()
      render(<TagAutocomplete onSelect={onSelect} {...props} />)
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: 'fo' } })

      await flushDebounce()

      expect(screen.getByRole('list')).toBeInTheDocument()
      return { onSelect, input, suggestions }
    }

    it('test_tagAutocomplete_clickSuggestion_callsOnSelectWithNamespacedTag', async () => {
      const { onSelect } = await renderWithSuggestions()
      const fooBtn = screen.getByText('foo').closest('button') as HTMLElement
      fireEvent.mouseDown(fooBtn)
      expect(onSelect).toHaveBeenCalledWith('artist:foo')
    })

    it('test_tagAutocomplete_clearOnSelectTrue_clearsInputAfterSelection', async () => {
      const { input } = await renderWithSuggestions({ clearOnSelect: true })
      const fooBtn = screen.getByText('foo').closest('button') as HTMLElement
      fireEvent.mouseDown(fooBtn)
      expect((input as HTMLInputElement).value).toBe('')
    })

    it('test_tagAutocomplete_clearOnSelectFalse_keepsTagInInputAfterSelection', async () => {
      const { input } = await renderWithSuggestions({ clearOnSelect: false })
      const fooBtn = screen.getByText('foo').closest('button') as HTMLElement
      fireEvent.mouseDown(fooBtn)
      expect((input as HTMLInputElement).value).toBe('artist:foo')
    })

    it('test_tagAutocomplete_afterSelection_dropdownCloses', async () => {
      await renderWithSuggestions()
      const fooBtn = screen.getByText('foo').closest('button') as HTMLElement
      fireEvent.mouseDown(fooBtn)
      expect(screen.queryByRole('list')).not.toBeInTheDocument()
    })
  })

  describe('keyboard navigation', () => {
    async function renderOpen() {
      const suggestions = [
        makeTag({ namespace: 'artist', name: 'alpha' }),
        makeTag({ id: 2, namespace: 'artist', name: 'beta' }),
      ]
      mockAutoComplete.mockResolvedValue(suggestions)

      const onSelect = vi.fn()
      render(<TagAutocomplete onSelect={onSelect} />)
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: 'al' } })

      await flushDebounce()

      expect(screen.getByRole('list')).toBeInTheDocument()
      return { onSelect, input }
    }

    it('test_tagAutocomplete_arrowDown_movesHighlightDown', async () => {
      const { input } = await renderOpen()
      fireEvent.keyDown(input, { key: 'ArrowDown' })
      // First suggestion (index 0) should be highlighted
      const list = screen.getByRole('list')
      const firstItemBtn = list.querySelectorAll('button')[0]
      // The highlighted item has vault-accent in its class
      expect(firstItemBtn.className).toContain('vault-accent')
    })

    it('test_tagAutocomplete_pressEnterOnHighlighted_callsOnSelect', async () => {
      const { onSelect, input } = await renderOpen()
      fireEvent.keyDown(input, { key: 'ArrowDown' })
      fireEvent.keyDown(input, { key: 'Enter' })
      expect(onSelect).toHaveBeenCalledWith('artist:alpha')
    })

    it('test_tagAutocomplete_pressEscape_closesDropdown', async () => {
      const { input } = await renderOpen()
      fireEvent.keyDown(input, { key: 'Escape' })
      expect(screen.queryByRole('list')).not.toBeInTheDocument()
    })
  })

  describe('empty query', () => {
    it('test_tagAutocomplete_emptyQuery_doesNotCallApi', async () => {
      render(<TagAutocomplete onSelect={vi.fn()} />)
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: '   ' } })

      await flushDebounce()

      expect(mockAutoComplete).not.toHaveBeenCalled()
    })
  })
})
