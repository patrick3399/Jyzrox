import { describe, it, expect } from 'vitest'
import {
  initialState,
  reducer,
  queryKey,
  ALL_CATS,
  buildParams,
  serializeSnapshot,
  parseSnapshot,
  parseUrlToIdentity,
  identityToUrlParams,
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
  it('search: all categories selected → no f_cats filter', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, { type: 'COMMIT_QUERY', query: 'foo' })
    const p = buildParams(s)
    expect(p.kind).toBe('search')
    expect(p.args).toMatchObject({ q: 'foo' })
    if (p.kind === 'search') expect(p.args.f_cats).toBeUndefined()
  })

  it('search: partial category selection → f_cats = ALL ^ selected', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, { type: 'SET_FILTER', patch: { advancedOpen: true, selectedCats: ['manga'] } })
    const p = buildParams(s)
    // manga bit = 4 → f_cats = 1023 ^ 4 = 1019
    if (p.kind === 'search') expect(p.args.f_cats).toBe(1019)
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
  it('caps items at 300 (keeps head)', () => {
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    const many = Array.from({ length: 500 }, (_, i) => g(i))
    s = reducer(s, { type: 'SEED', items: many, total: 500, cursor: null, hasMore: false })
    const snap = JSON.parse(serializeSnapshot(s))
    expect(snap.items).toHaveLength(300)
    expect(snap.items[0].gid).toBe(0)
    expect(snap.queryKey).toBe(queryKey(s))
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
