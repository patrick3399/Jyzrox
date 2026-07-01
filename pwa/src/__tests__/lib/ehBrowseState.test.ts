import { describe, it, expect } from 'vitest'
import { initialState, reducer, queryKey, ALL_CATS } from '@/lib/ehBrowseState'

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
