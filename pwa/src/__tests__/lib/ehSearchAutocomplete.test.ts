import { describe, expect, it } from 'vitest'
import {
  applyEhAutocompleteSuggestion,
  getEhAutocompleteFragment,
} from '@/lib/ehSearchAutocomplete'

describe('EH search autocomplete composition', () => {
  it('queries only the unfinished final token', () => {
    expect(getEhAutocompleteFragment('artist:foo f:big bre')).toEqual({
      start: 11,
      query: 'female:big bre',
      excluded: false,
    })
  })

  it('preserves preceding tokens and exclusion when applying a suggestion', () => {
    const value = 'language:chinese -f:big bre'
    const fragment = getEhAutocompleteFragment(value)
    expect(fragment).not.toBeNull()
    expect(
      applyEhAutocompleteSuggestion(value, fragment!, {
        namespace: 'female',
        name: 'big breasts',
      }),
    ).toBe('language:chinese -female:"big breasts$" ')
  })

  it('does not reopen autocomplete for an exact completed tag', () => {
    expect(getEhAutocompleteFragment('artist:foo$')).toBeNull()
    expect(getEhAutocompleteFragment('artist:"foo bar$"')).toBeNull()
  })

  // applyEhAutocompleteSuggestion always appends a separator space, so the
  // value it produces must itself parse as "nothing left to complete".
  it('does not reopen autocomplete when a completed tag is followed by whitespace', () => {
    expect(getEhAutocompleteFragment('artist:foo$ ')).toBeNull()
    expect(getEhAutocompleteFragment('artist:"foo bar$" ')).toBeNull()

    const fragment = getEhAutocompleteFragment('fem')
    expect(fragment).not.toBeNull()
    const applied = applyEhAutocompleteSuggestion('fem', fragment!, {
      namespace: 'female',
      name: 'big breasts',
    })
    expect(getEhAutocompleteFragment(applied)).toBeNull()
  })

  it('still completes the next token typed after a completed tag', () => {
    expect(getEhAutocompleteFragment('artist:foo$ bar')).toEqual({
      start: 12,
      query: 'bar',
      excluded: false,
    })
  })
})
