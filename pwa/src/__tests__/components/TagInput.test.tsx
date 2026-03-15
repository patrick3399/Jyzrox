/**
 * TagInput — Vitest test suite
 *
 * Covers:
 *   - Renders include and exclude label sections
 *   - Renders existing include tags as TagBadge components
 *   - Renders existing exclude tags as TagBadge components
 *   - Pressing Enter in include input calls onAddInclude with trimmed lowercase
 *   - Pressing Enter in exclude input calls onAddExclude with trimmed lowercase
 *   - Pressing Enter with empty input does not call onAdd
 *   - Pressing Enter with duplicate tag does not call onAdd
 *   - Clicking remove button on an include tag calls onRemoveInclude
 *   - Clicking remove button on an exclude tag calls onRemoveExclude
 *   - Input clears after Enter press
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/components/TagBadge', () => ({
  TagBadge: ({ tag, onRemove }: { tag: string; onRemove?: () => void }) => (
    <span data-testid={`tag-badge-${tag}`}>
      {tag}
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`remove-${tag}`}>
          x
        </button>
      )}
    </span>
  ),
}))

// ── Import component after mocks ───────────────────────────────────────

import { TagInput } from '@/components/TagInput'

// ── Default props factory ──────────────────────────────────────────────

function makeProps(overrides: Partial<React.ComponentProps<typeof TagInput>> = {}) {
  return {
    includeTags: [],
    excludeTags: [],
    onAddInclude: vi.fn(),
    onRemoveInclude: vi.fn(),
    onAddExclude: vi.fn(),
    onRemoveExclude: vi.fn(),
    ...overrides,
  }
}

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('TagInput', () => {
  describe('label rendering', () => {
    it('test_tagInput_rendersIncludeTagsLabel', () => {
      render(<TagInput {...makeProps()} />)
      expect(screen.getByText('Include Tags')).toBeInTheDocument()
    })

    it('test_tagInput_rendersExcludeTagsLabel', () => {
      render(<TagInput {...makeProps()} />)
      expect(screen.getByText('Exclude Tags')).toBeInTheDocument()
    })
  })

  describe('existing tags', () => {
    it('test_tagInput_withIncludeTags_rendersBadgesForEach', () => {
      render(<TagInput {...makeProps({ includeTags: ['artist:foo', 'character:bar'] })} />)
      expect(screen.getByTestId('tag-badge-artist:foo')).toBeInTheDocument()
      expect(screen.getByTestId('tag-badge-character:bar')).toBeInTheDocument()
    })

    it('test_tagInput_withExcludeTags_rendersBadgesForEach', () => {
      render(<TagInput {...makeProps({ excludeTags: ['general:baz'] })} />)
      expect(screen.getByTestId('tag-badge-general:baz')).toBeInTheDocument()
    })

    it('test_tagInput_emptyTags_rendersNoBadges', () => {
      render(<TagInput {...makeProps()} />)
      expect(screen.queryByTestId(/^tag-badge-/)).not.toBeInTheDocument()
    })
  })

  describe('adding tags via Enter', () => {
    it('test_tagInput_pressEnterInIncludeInput_callsOnAddInclude', async () => {
      const user = userEvent.setup()
      const props = makeProps()
      render(<TagInput {...props} />)
      const includeInput = screen.getByLabelText('Include Tags')
      await user.type(includeInput, 'newtag{Enter}')
      expect(props.onAddInclude).toHaveBeenCalledWith('newtag')
    })

    it('test_tagInput_pressEnterInExcludeInput_callsOnAddExclude', async () => {
      const user = userEvent.setup()
      const props = makeProps()
      render(<TagInput {...props} />)
      const excludeInput = screen.getByLabelText('Exclude Tags')
      await user.type(excludeInput, 'excludetag{Enter}')
      expect(props.onAddExclude).toHaveBeenCalledWith('excludetag')
    })

    it('test_tagInput_pressEnterWithWhitespace_callsTrimmedLowercase', async () => {
      const user = userEvent.setup()
      const props = makeProps()
      render(<TagInput {...props} />)
      const includeInput = screen.getByLabelText('Include Tags')
      await user.type(includeInput, '  MixedCase  {Enter}')
      expect(props.onAddInclude).toHaveBeenCalledWith('mixedcase')
    })

    it('test_tagInput_pressEnterWithEmptyInput_doesNotCallOnAdd', async () => {
      const user = userEvent.setup()
      const props = makeProps()
      render(<TagInput {...props} />)
      const includeInput = screen.getByLabelText('Include Tags')
      await user.click(includeInput)
      await user.keyboard('{Enter}')
      expect(props.onAddInclude).not.toHaveBeenCalled()
    })

    it('test_tagInput_pressEnterWithDuplicateTag_doesNotCallOnAdd', async () => {
      const user = userEvent.setup()
      const props = makeProps({ includeTags: ['existing'] })
      render(<TagInput {...props} />)
      const includeInput = screen.getByLabelText('Include Tags')
      await user.type(includeInput, 'existing{Enter}')
      expect(props.onAddInclude).not.toHaveBeenCalled()
    })

    it('test_tagInput_afterPressEnter_inputClears', async () => {
      const user = userEvent.setup()
      render(<TagInput {...makeProps()} />)
      const includeInput = screen.getByLabelText('Include Tags') as HTMLInputElement
      await user.type(includeInput, 'sometag{Enter}')
      expect(includeInput.value).toBe('')
    })
  })

  describe('removing tags', () => {
    it('test_tagInput_clickRemoveOnIncludeTag_callsOnRemoveInclude', async () => {
      const user = userEvent.setup()
      const props = makeProps({ includeTags: ['artist:foo'] })
      render(<TagInput {...props} />)
      await user.click(screen.getByLabelText('remove-artist:foo'))
      expect(props.onRemoveInclude).toHaveBeenCalledWith('artist:foo')
    })

    it('test_tagInput_clickRemoveOnExcludeTag_callsOnRemoveExclude', async () => {
      const user = userEvent.setup()
      const props = makeProps({ excludeTags: ['general:baz'] })
      render(<TagInput {...props} />)
      await user.click(screen.getByLabelText('remove-general:baz'))
      expect(props.onRemoveExclude).toHaveBeenCalledWith('general:baz')
    })
  })
})
