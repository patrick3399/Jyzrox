import { describe, expect, it } from 'vitest'
import { canonicalIdentityKey, normalizeBrowseIdentity } from '@/lib/browse/identity'

describe('browse identity contracts', () => {
  it('canonicalizes nested object keys without depending on insertion order', () => {
    const first = {
      surface: 'search',
      filters: { rating: 3, tags: ['artist:a', 'language:en'] },
      paging: { limit: 24, sort: 'added_at' },
    }
    const second = {
      paging: { sort: 'added_at', limit: 24 },
      filters: { tags: ['artist:a', 'language:en'], rating: 3 },
      surface: 'search',
    }

    expect(canonicalIdentityKey(first)).toBe(canonicalIdentityKey(second))
  })

  it('keeps array order explicit until the surface normalization hook changes it', () => {
    const forward = { surface: 'search', tags: ['artist:a', 'language:en'] }
    const reverse = { surface: 'search', tags: ['language:en', 'artist:a'] }

    expect(canonicalIdentityKey(forward)).not.toBe(canonicalIdentityKey(reverse))

    const hooks = {
      search: (identity: typeof forward) => ({
        ...identity,
        tags: [...identity.tags].sort(),
      }),
    }
    expect(canonicalIdentityKey(normalizeBrowseIdentity(forward, hooks))).toBe(
      canonicalIdentityKey(normalizeBrowseIdentity(reverse, hooks)),
    )
  })

  it('runs only the hook registered for the current surface', () => {
    const identity = { surface: 'ranking', mode: '', content: '', r18: true }
    const normalized = normalizeBrowseIdentity(identity, {
      search: () => ({ surface: 'search', query: 'wrong hook' }),
      ranking: (value) => ({
        ...value,
        mode: value.mode || 'daily',
        content: value.r18 ? 'all' : value.content || 'all',
      }),
    })

    expect(normalized).toEqual({ surface: 'ranking', mode: 'daily', content: 'all', r18: true })
  })

  it('lets a surface normalizer deduplicate and order multivalue identity fields', () => {
    type SearchIdentity = { surface: 'search'; tags: string[] }
    const normalize = (value: SearchIdentity): SearchIdentity => ({
      ...value,
      tags: [...new Set(value.tags)].sort(),
    })
    const noisy: SearchIdentity = {
      surface: 'search',
      tags: ['language:en', 'artist:a', 'language:en'],
    }
    const canonical: SearchIdentity = {
      surface: 'search',
      tags: ['artist:a', 'language:en'],
    }

    expect(canonicalIdentityKey(normalizeBrowseIdentity(noisy, { search: normalize }))).toBe(
      canonicalIdentityKey(normalizeBrowseIdentity(canonical, { search: normalize })),
    )
  })

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    'normalizes a non-finite identity number to the JSON-safe null value (%s)',
    (invalid) => {
      expect(canonicalIdentityKey({ surface: 'search', rating: invalid })).toBe(
        canonicalIdentityKey({ surface: 'search', rating: null }),
      )
    },
  )
})
