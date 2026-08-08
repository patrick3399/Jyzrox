import { describe, expect, it } from 'vitest'
import {
  buildParamsFromIdentity,
  identityToUrlParams,
  initialState,
  parseUrlToIdentity,
  queryKey,
  reducer,
  serializeSnapshot,
} from '@/lib/ehBrowseState'
import { canonicalEhIdentity } from '@/lib/browse/ehentai'

function apply(
  tab: 'search' | 'favorites' | 'popular' | 'toplist',
  patch: Partial<typeof initialState.filters> = {},
) {
  let state = reducer(initialState, { type: 'SET_TAB', tab })
  state = reducer(state, { type: 'SET_FILTER', patch })
  return state
}

describe('E-Hentai browse-session canonical identity', () => {
  it('builds requests from the coordinator identity instead of a stale view ref', () => {
    const popular = canonicalEhIdentity(apply('popular'))
    const latest = canonicalEhIdentity(apply('search'))
    const toplist = canonicalEhIdentity(apply('toplist', { toplistTl: 13 }))

    expect(buildParamsFromIdentity(popular, null)).toEqual({ kind: 'popular', args: {} })
    expect(buildParamsFromIdentity(latest, null)).toEqual({
      kind: 'search',
      args: { q: undefined, f_cats: undefined },
    })
    expect(buildParamsFromIdentity(toplist, null)).toEqual({
      kind: 'toplist',
      args: { tl: 13, page: 0 },
    })
  })

  it.each(['-1', '1.5', '2048', 'Infinity', 'not-a-number'])(
    'normalizes illegal advanced-search mask %s to the default',
    (adv) => {
      const malformed = { ...initialState, ...parseUrlToIdentity(new URLSearchParams(`q=x&adv=${adv}`)) }
      const canonical = { ...initialState, ...parseUrlToIdentity(new URLSearchParams('q=x')) }

      expect(queryKey(malformed)).toBe(queryKey(canonical))
      expect(identityToUrlParams(malformed).toString()).toBe('q=x')
    },
  )

  it('deduplicates and sorts categories before identity and URL serialization', () => {
    const duplicated = {
      ...initialState,
      ...parseUrlToIdentity(new URLSearchParams('q=x&cat=manga,doujinshi,manga,manga')),
    }
    const canonical = {
      ...initialState,
      ...parseUrlToIdentity(new URLSearchParams('q=x&cat=doujinshi,manga')),
    }

    expect(queryKey(duplicated)).toBe(queryKey(canonical))
    expect(identityToUrlParams(duplicated).toString()).toBe(
      identityToUrlParams(canonical).toString(),
    )
  })

  it('popular ignores favorites, toplist, and panel-only fields', () => {
    const canonical = apply('popular')
    const polluted = apply('popular', {
      favCat: '7',
      favSearch: 'old favorite',
      toplistTl: 13,
      advancedOpen: true,
    })

    expect(queryKey(polluted)).toBe(queryKey(canonical))
    expect(identityToUrlParams(polluted).toString()).toBe(
      identityToUrlParams(canonical).toString(),
    )
  })

  it('favorites ignores search-only, toplist, and panel-only fields when round-tripped', () => {
    const canonical = apply('favorites', { favCat: '3', favSearch: 'needle' })
    const polluted = apply('favorites', {
      favCat: '3',
      favSearch: 'needle',
      selectedCats: ['manga'],
      advSearch: 0x80,
      minRating: 4,
      pageFrom: 20,
      pageTo: 80,
      language: 'chinese',
      toplistTl: 15,
      advancedOpen: true,
    })

    expect(queryKey(polluted)).toBe(queryKey(canonical))
    const params = identityToUrlParams(polluted)
    expect(params.has('cat')).toBe(false)
    expect(params.has('adv_open')).toBe(false)
    expect(params.has('adv')).toBe(false)
    expect(params.has('minrating')).toBe(false)
    expect(params.has('pfrom')).toBe(false)
    expect(params.has('pto')).toBe(false)
    expect(params.has('language')).toBe(false)
    expect(params.has('tl')).toBe(false)
    expect(queryKey({ ...polluted, ...parseUrlToIdentity(params) })).toBe(queryKey(canonical))
  })

  it('toplist ignores favorites, search-only, and panel-only fields when round-tripped', () => {
    const canonical = apply('toplist', { toplistTl: 13 })
    const polluted = apply('toplist', {
      toplistTl: 13,
      favCat: '5',
      favSearch: 'stale',
      selectedCats: ['cosplay'],
      advSearch: 0x20,
      minRating: 5,
      advancedOpen: true,
    })

    expect(queryKey(polluted)).toBe(queryKey(canonical))
    const params = identityToUrlParams(polluted)
    expect(params.toString()).toBe('tab=toplist&tl=13')
    expect(queryKey({ ...polluted, ...parseUrlToIdentity(params) })).toBe(queryKey(canonical))
  })

  it('search identity ignores favorites, toplist, and panel expansion state', () => {
    let canonical = apply('search', {
      selectedCats: ['manga'],
      advSearch: 0x80,
      minRating: 4,
    })
    canonical = reducer(canonical, { type: 'COMMIT_QUERY', query: 'artist:foo' })
    let polluted = apply('search', {
      selectedCats: ['manga'],
      advSearch: 0x80,
      minRating: 4,
      favCat: '9',
      favSearch: 'stale',
      toplistTl: 15,
      advancedOpen: true,
    })
    polluted = reducer(polluted, { type: 'COMMIT_QUERY', query: 'artist:foo' })

    expect(queryKey(polluted)).toBe(queryKey(canonical))
  })
})

describe('E-Hentai browse-session retention contract', () => {
  it('retains a deep chain beyond five logical identities', () => {
    let raw: string | null = null
    const keys: string[] = []

    for (let index = 0; index < 7; index += 1) {
      let state = apply('search')
      state = reducer(state, { type: 'COMMIT_QUERY', query: `chain-${index}` })
      state = reducer(state, {
        type: 'SEED',
        items: [{ gid: index + 1, token: `token-${index}` } as never],
        total: 1,
        cursor: null,
        hasMore: false,
      })
      keys.push(queryKey(state))
      raw = serializeSnapshot(state, raw)
    }

    const store = JSON.parse(raw ?? '{}') as { snaps?: { queryKey: string }[] }
    expect(store.snaps?.map((snapshot) => snapshot.queryKey)).toEqual(
      [...keys].reverse(),
    )
  })
})
