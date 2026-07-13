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
})
