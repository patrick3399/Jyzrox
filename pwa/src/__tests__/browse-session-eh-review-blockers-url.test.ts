import { describe, expect, it } from 'vitest'
import {
  buildParams,
  identityToUrlParams,
  initialState,
  parseUrlToIdentity,
  queryKey,
  type EhBrowseState,
} from '@/lib/ehBrowseState'

function stateFromUrl(url: string): EhBrowseState {
  return { ...initialState, ...parseUrlToIdentity(new URLSearchParams(url)) }
}

describe('E-Hentai review blockers — malformed URL normalization', () => {
  it('normalizes malformed toplist period before identity, fetch planning, and roundtrip', () => {
    const malformed = stateFromUrl('tab=toplist&tl=not-a-number')
    const canonical = stateFromUrl('tab=toplist')

    expect(queryKey(malformed)).toBe(queryKey(canonical))
    expect(buildParams(malformed)).toEqual(buildParams(canonical))
    expect(identityToUrlParams(malformed).toString()).toBe('tab=toplist')
  })

  it('normalizes malformed numeric search filters before identity, fetch planning, and roundtrip', () => {
    const malformed = stateFromUrl('q=artist%3Afoo&minrating=bogus&pfrom=-2&pto=Infinity')
    const canonical = stateFromUrl('q=artist%3Afoo')

    expect(queryKey(malformed)).toBe(queryKey(canonical))
    expect(buildParams(malformed)).toEqual(buildParams(canonical))
    expect(identityToUrlParams(malformed).toString()).toBe('q=artist%3Afoo')
  })

  it('normalizes invalid favorites category enums to the all-category default', () => {
    const malformed = stateFromUrl('tab=favorites&favcat=invalid')
    const canonical = stateFromUrl('tab=favorites')

    expect(queryKey(malformed)).toBe(queryKey(canonical))
    expect(buildParams(malformed)).toEqual(buildParams(canonical))
    expect(identityToUrlParams(malformed).toString()).toBe('tab=favorites')
  })
})
