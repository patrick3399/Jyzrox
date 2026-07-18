import { describe, it, expect } from 'vitest'
import {
  initialState,
  reducer,
  queryKey,
  ALL_CATS,
  buildParams,
  EH_ADVANCED_SEARCH_BITS,
  serializeSnapshot,
  parseSnapshot,
  parseUrlToIdentity,
  identityToUrlParams,
  parseEhSavedSearch,
  serializeEhSavedSearchParams,
} from '@/lib/ehBrowseState'

describe('ehBrowseState — queryKey & identity reset', () => {
  it('queryKey is stable when re-selecting the same value', () => {
    const s1 = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    const s2 = reducer(s1, { type: 'SET_TAB', tab: 'search' })
    expect(queryKey(s1)).toBe(queryKey(s2))
  })

  it('changing query resets the accumulated view', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, {
      type: 'SEED',
      items: [{ gid: 1, token: 'a' } as never],
      total: 5,
      cursor: { kind: 'gid', nextGid: 100 },
      hasMore: true,
    })
    expect(s.items).toHaveLength(1)
    const after = reducer(s, { type: 'COMMIT_QUERY', query: 'naruto' })
    expect(after.items).toHaveLength(0)
    expect(after.cursor).toBeNull()
    expect(after.hasMore).toBe(true)
    expect(after.scrollY).toBe(0)
  })

  it('toggling advancedOpen changes queryKey (it affects search semantics)', () => {
    const s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    const adv = reducer(s, { type: 'SET_FILTER', patch: { advancedOpen: true } })
    expect(queryKey(s)).not.toBe(queryKey(adv))
    expect(adv.items).toHaveLength(0)
  })

  it('ALL_CATS has all 10 categories', () => {
    expect(ALL_CATS).toHaveLength(10)
  })
})

describe('ehBrowseState — saved search identity', () => {
  it('round-trips the full EH filter identity', () => {
    let state = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    state = reducer(state, { type: 'COMMIT_QUERY', query: 'artist:foo' })
    state = reducer(state, {
      type: 'SET_FILTER',
      patch: {
        selectedCats: ['manga'],
        advancedOpen: true,
        advSearch: EH_ADVANCED_SEARCH_BITS.showExpunged,
        minRating: 4,
        pageFrom: 20,
        pageTo: 80,
        language: 'chinese',
      },
    })

    const restored = parseEhSavedSearch(state.query, serializeEhSavedSearchParams(state))
    expect(restored).toEqual({ tab: state.tab, query: state.query, filters: state.filters })
  })

  it('keeps old query-only saved searches compatible', () => {
    const restored = parseEhSavedSearch('language:chinese', {})
    expect(restored.tab).toBe('search')
    expect(restored.query).toBe('language:chinese')
    expect(restored.filters).toEqual(initialState.filters)
  })
})

describe('ehBrowseState — SEED/APPEND', () => {
  const g = (gid: number) => ({ gid, token: `t${gid}` }) as never
  it('APPEND dedupes by gid', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, {
      type: 'SEED',
      items: [g(1), g(2)],
      total: 9,
      cursor: { kind: 'gid', nextGid: 3 },
      hasMore: true,
    })
    s = reducer(s, {
      type: 'APPEND',
      items: [g(2), g(3)],
      cursor: { kind: 'gid', nextGid: 4 },
      hasMore: true,
    })
    expect(s.items.map((x) => x.gid)).toEqual([1, 2, 3])
  })
  it('SEED replaces the buffer and captures total', () => {
    let s = reducer(initialState, {
      type: 'SEED',
      items: [g(1)],
      total: 3,
      cursor: null,
      hasMore: false,
    })
    s = reducer(s, { type: 'SEED', items: [g(5)], total: 7, cursor: null, hasMore: false })
    expect(s.items.map((x) => x.gid)).toEqual([5])
    expect(s.total).toBe(7)
  })
})

describe('ehBrowseState — buildParams', () => {
  it('uses the EH flag assignments for low-power, downvoted, and expunged results', () => {
    expect(EH_ADVANCED_SEARCH_BITS.lowPowerTags).toBe(0x20)
    expect(EH_ADVANCED_SEARCH_BITS.downvotedTags).toBe(0x40)
    expect(EH_ADVANCED_SEARCH_BITS.showExpunged).toBe(0x80)
  })

  it('search: all categories selected → no f_cats filter', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, { type: 'COMMIT_QUERY', query: 'foo' })
    const p = buildParams(s)
    expect(p.kind).toBe('search')
    expect(p.args).toMatchObject({ q: 'foo' })
    if (p.kind === 'search') expect(p.args.f_cats).toBeUndefined()
  })

  it('search: partial category selection → f_cats = ALL ^ selected (even with advanced closed)', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, { type: 'SET_FILTER', patch: { selectedCats: ['manga'] } })
    const p = buildParams(s)
    // manga bit = 4 → f_cats = 1023 ^ 4 = 1019, regardless of advancedOpen
    if (p.kind === 'search') expect(p.args.f_cats).toBe(1019)
    expect(s.filters.advancedOpen).toBe(false)
  })

  it('search: cursor carries next_gid on append', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, {
      type: 'SEED',
      items: [],
      total: 0,
      cursor: { kind: 'gid', nextGid: 42 },
      hasMore: true,
    })
    const p = buildParams(s)
    if (p.kind === 'search') expect(p.args.next_gid).toBe(42)
  })

  it('favorites: builds favcat + q + next', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'favorites' })
    s = reducer(s, { type: 'SET_FILTER', patch: { favCat: '3', favSearch: 'x' } })
    s = reducer(s, {
      type: 'SEED',
      items: [],
      total: 0,
      cursor: { kind: 'fav', next: 'CUR' },
      hasMore: true,
    })
    const p = buildParams(s)
    expect(p.kind).toBe('favorites')
    expect(p.args).toMatchObject({ favcat: '3', q: 'x', next: 'CUR' })
  })

  it('toplist: builds tl + page', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'toplist' })
    s = reducer(s, { type: 'SET_FILTER', patch: { toplistTl: 13 } })
    s = reducer(s, {
      type: 'SEED',
      items: [],
      total: 0,
      cursor: { kind: 'page', page: 2 },
      hasMore: true,
    })
    const p = buildParams(s)
    expect(p).toMatchObject({ kind: 'toplist', args: { tl: 13, page: 2 } })
  })

  it('popular: no args', () => {
    const s = reducer(initialState, { type: 'SET_TAB', tab: 'popular' })
    expect(buildParams(s).kind).toBe('popular')
  })
})

describe('ehBrowseState — snapshot', () => {
  const g = (gid: number) => ({ gid, token: `t${gid}` }) as never
  it('keeps the full item buffer aligned with its cursor and scroll after 300 items', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    const many = Array.from({ length: 500 }, (_, i) => g(i))
    s = reducer(s, {
      type: 'SEED',
      items: many,
      total: 1000,
      cursor: { kind: 'gid', nextGid: 500 },
      hasMore: true,
    })
    s = reducer(s, { type: 'SET_SCROLL', scrollY: 24000 })
    const store = JSON.parse(serializeSnapshot(s))
    expect(store.version).toBe(2)
    expect(store.snaps).toHaveLength(1)
    expect(store.snaps[0].items).toHaveLength(500)
    expect(store.snaps[0].items[0].gid).toBe(0)
    expect(store.snaps[0].items[499].gid).toBe(499)
    expect(store.snaps[0].cursor).toEqual({ kind: 'gid', nextGid: 500 })
    expect(store.snaps[0].scrollY).toBe(24000)
    expect(store.snaps[0].queryKey).toBe(queryKey(s))
  })

  it('keeps one snapshot per identity, MRU-first, evicting beyond the history cap', () => {
    // 6 different search identities → oldest falls out of the 5-slot store.
    let raw: string | null = null
    for (let i = 0; i < 6; i++) {
      let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
      s = reducer(s, { type: 'COMMIT_QUERY', query: `q${i}` })
      s = reducer(s, { type: 'SEED', items: [g(i)], total: 1, cursor: null, hasMore: false })
      raw = serializeSnapshot(s, raw)
    }
    const store = JSON.parse(raw!)
    expect(store.snaps).toHaveLength(5)
    // MRU order: q5 first, q1 last; q0 evicted.
    expect(store.snaps[0].items[0].gid).toBe(5)
    expect(store.snaps.some((x: { items: { gid: number }[] }) => x.items[0].gid === 0)).toBe(false)

    // Re-banking an existing identity replaces its slot instead of duplicating.
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, { type: 'COMMIT_QUERY', query: 'q3' })
    s = reducer(s, { type: 'SEED', items: [g(99)], total: 1, cursor: null, hasMore: false })
    const store2 = JSON.parse(serializeSnapshot(s, raw))
    expect(store2.snaps).toHaveLength(5)
    expect(store2.snaps[0].items[0].gid).toBe(99)
    expect(
      store2.snaps.filter((x: { queryKey: string }) => x.queryKey === queryKey(s)),
    ).toHaveLength(1)
  })
  it('parseSnapshot returns null when queryKey mismatches', () => {
    const s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    const raw = serializeSnapshot(s)
    expect(parseSnapshot(raw, 'DIFFERENT_KEY')).toBeNull()
  })
  it('parseSnapshot returns view when queryKey matches', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, {
      type: 'SEED',
      items: [g(1)],
      total: 1,
      cursor: { kind: 'gid', nextGid: 2 },
      hasMore: true,
    })
    s = reducer(s, { type: 'SET_SCROLL', scrollY: 640 })
    const restored = parseSnapshot(serializeSnapshot(s), queryKey(s))
    expect(restored?.items).toHaveLength(1)
    expect(restored?.scrollY).toBe(640)
    expect(restored?.cursor).toEqual({ kind: 'gid', nextGid: 2 })
  })
  it('parseSnapshot tolerates malformed JSON', () => {
    expect(parseSnapshot('{not json', 'k')).toBeNull()
    expect(parseSnapshot('', 'k')).toBeNull()
  })

  it('rejects legacy snapshots that may mix a truncated buffer with a later cursor', () => {
    const legacy = JSON.stringify({
      snaps: [
        {
          queryKey: 'search',
          items: [g(1)],
          cursor: { kind: 'gid', nextGid: 999 },
          hasMore: true,
          scrollY: 50000,
        },
      ],
    })
    expect(parseSnapshot(legacy, 'search')).toBeNull()
  })
})

describe('ehBrowseState — URL identity', () => {
  const g = (gid: number) => ({ gid, token: `t${gid}` }) as never
  it('round-trips identity through URL params', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'favorites' })
    s = reducer(s, { type: 'SET_FILTER', patch: { favCat: '5', favSearch: 'zzz' } })
    const params = identityToUrlParams(s)
    const parsed = parseUrlToIdentity(new URLSearchParams(params.toString()))
    expect(parsed.tab).toBe('favorites')
    expect(parsed.filters.favCat).toBe('5')
    expect(parsed.filters.favSearch).toBe('zzz')
  })
  it('empty params → popular default identity', () => {
    const parsed = parseUrlToIdentity(new URLSearchParams(''))
    expect(parsed.tab).toBe('popular')
    expect(parsed.query).toBe('')
  })
  // Regression: the Latest tab (search + empty query) MUST serialize to a
  // non-empty URL. It shares a bare URL with the popular default otherwise, and
  // useEhBrowse's "externally-cleared URL → reset to popular" effect (keyed on
  // searchParams.toString() === '') fires when navigating Popular → Latest,
  // bouncing the user straight back to Popular.
  it('latest tab (search + empty query) does not serialize to a bare URL', () => {
    const s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    expect(s.query).toBe('')
    const str = identityToUrlParams(s).toString()
    expect(str).not.toBe('')
    const parsed = parseUrlToIdentity(new URLSearchParams(str))
    expect(parsed.tab).toBe('search')
    expect(parsed.query).toBe('')
  })
  it('search tab WITH a query stays bare of the redundant tab marker', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, { type: 'COMMIT_QUERY', query: 'naruto' })
    const str = identityToUrlParams(s).toString()
    // q= alone already implies the search tab; no need for tab=search.
    expect(str).not.toMatch(/tab=/)
    expect(str).toMatch(/q=naruto/)
  })
  it('URL params never contain view fields', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, {
      type: 'SEED',
      items: [g(1)],
      total: 1,
      cursor: { kind: 'gid', nextGid: 9 },
      hasMore: true,
    })
    const str = identityToUrlParams(s).toString()
    expect(str).not.toMatch(/gid|scroll|items|cursor/i)
  })
})

