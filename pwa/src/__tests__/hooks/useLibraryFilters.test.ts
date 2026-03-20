/**
 * useLibraryFilters — Vitest test suite
 *
 * Covers:
 *   initFilterState() — parses URLSearchParams into FilterState defaults
 *   initFilterState() — parses q, tags, notags, rating, fav, source params
 *   filterReducer()   — SET_SEARCH_INPUT updates searchInput
 *   filterReducer()   — ADD_INCLUDE_TAG adds tag and clears includeInput
 *   filterReducer()   — ADD_INCLUDE_TAG deduplicates existing tags
 *   filterReducer()   — ADD_INCLUDE_TAG ignores empty/whitespace payloads
 *   filterReducer()   — REMOVE_INCLUDE_TAG removes the specified tag
 *   filterReducer()   — SET_SORT updates sort field
 *   filterReducer()   — TOGGLE_SELECTED_ID adds then removes an id
 *   filterReducer()   — CLEAR_SELECTION resets selectedIds and selectMode
 *   useLibraryFilters — URL sync is debounced by 500ms
 *   useLibraryFilters — handleSearchChange debounces searchQuery by 400ms
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations, so any variables
 *   referenced inside a factory must be declared with vi.hoisted() to guarantee
 *   they exist at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockReplace } = vi.hoisted(() => ({
  mockReplace: vi.fn(),
}))

// ── Module mocks ──────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: mockReplace }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

// ── Import hook and helpers after mocks ───────────────────────────────

import { useLibraryFilters, filterReducer, initFilterState } from '@/hooks/useLibraryFilters'

// ── Shared setup ──────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── initFilterState tests ─────────────────────────────────────────────

describe('initFilterState — defaults', () => {
  it('should return all defaults when URLSearchParams is empty', () => {
    const state = initFilterState(new URLSearchParams())

    expect(state.searchQuery).toBe('')
    expect(state.searchInput).toBe('')
    expect(state.includeTags).toEqual([])
    expect(state.excludeTags).toEqual([])
    expect(state.includeInput).toBe('')
    expect(state.excludeInput).toBe('')
    expect(state.minRating).toBeUndefined()
    expect(state.onlyFavorited).toBe(false)
    expect(state.sourceFilter).toBe('')
    expect(state.sort).toBe('added_at')
    expect(state.selectMode).toBe(false)
    expect(state.selectedIds.size).toBe(0)
  })

  it('should parse ?q=test into searchQuery and searchInput', () => {
    const state = initFilterState(new URLSearchParams('q=test'))

    expect(state.searchQuery).toBe('test')
    expect(state.searchInput).toBe('test')
  })

  it('should parse ?tags=a,b into includeTags array', () => {
    const state = initFilterState(new URLSearchParams('tags=a,b'))

    expect(state.includeTags).toEqual(['a', 'b'])
  })

  it('should parse ?notags=x into excludeTags array', () => {
    const state = initFilterState(new URLSearchParams('notags=x'))

    expect(state.excludeTags).toEqual(['x'])
  })

  it('should parse ?rating=3 into minRating=3', () => {
    const state = initFilterState(new URLSearchParams('rating=3'))

    expect(state.minRating).toBe(3)
  })

  it('should parse ?fav=1 into onlyFavorited=true', () => {
    const state = initFilterState(new URLSearchParams('fav=1'))

    expect(state.onlyFavorited).toBe(true)
  })

  it('should parse ?source=eh:download into sourceFilter', () => {
    const state = initFilterState(new URLSearchParams('source=eh:download'))

    expect(state.sourceFilter).toBe('eh:download')
  })
})

// ── filterReducer tests ───────────────────────────────────────────────

describe('filterReducer', () => {
  const base = initFilterState(new URLSearchParams())

  it('SET_SEARCH_INPUT should update searchInput', () => {
    const next = filterReducer(base, { type: 'SET_SEARCH_INPUT', payload: 'hello' })

    expect(next.searchInput).toBe('hello')
  })

  it('ADD_INCLUDE_TAG should add tag and clear includeInput', () => {
    const next = filterReducer(base, { type: 'ADD_INCLUDE_TAG', payload: 'artist:foo' })

    expect(next.includeTags).toEqual(['artist:foo'])
    expect(next.includeInput).toBe('')
  })

  it('ADD_INCLUDE_TAG should not add a duplicate tag', () => {
    const withTag = filterReducer(base, { type: 'ADD_INCLUDE_TAG', payload: 'artist:foo' })
    const withDupe = filterReducer(withTag, { type: 'ADD_INCLUDE_TAG', payload: 'artist:foo' })

    expect(withDupe.includeTags).toHaveLength(1)
    expect(withDupe.includeTags).toEqual(['artist:foo'])
  })

  it('ADD_INCLUDE_TAG should ignore empty/whitespace-only payloads', () => {
    const next = filterReducer(base, { type: 'ADD_INCLUDE_TAG', payload: '  ' })

    expect(next.includeTags).toHaveLength(0)
  })

  it('REMOVE_INCLUDE_TAG should remove the specified tag', () => {
    const withTag = filterReducer(base, { type: 'ADD_INCLUDE_TAG', payload: 'artist:foo' })
    const removed = filterReducer(withTag, { type: 'REMOVE_INCLUDE_TAG', payload: 'artist:foo' })

    expect(removed.includeTags).toHaveLength(0)
  })

  it('SET_SORT should update the sort field', () => {
    const next = filterReducer(base, { type: 'SET_SORT', payload: 'rating' })

    expect(next.sort).toBe('rating')
  })

  it('TOGGLE_SELECTED_ID should add an id then remove it on second toggle', () => {
    const added = filterReducer(base, { type: 'TOGGLE_SELECTED_ID', payload: 5 })
    expect(added.selectedIds.has(5)).toBe(true)

    const removed = filterReducer(added, { type: 'TOGGLE_SELECTED_ID', payload: 5 })
    expect(removed.selectedIds.has(5)).toBe(false)
  })

  it('CLEAR_SELECTION should reset selectedIds to empty Set and selectMode to false', () => {
    const withSelection = filterReducer(
      { ...base, selectedIds: new Set([1, 2, 3]), selectMode: true },
      { type: 'CLEAR_SELECTION' },
    )

    expect(withSelection.selectedIds.size).toBe(0)
    expect(withSelection.selectMode).toBe(false)
  })
})

// ── Hook integration tests ────────────────────────────────────────────

describe('useLibraryFilters — URL sync debounce', () => {
  it('should debounce URL sync by 500ms', () => {
    vi.useFakeTimers()

    const { result } = renderHook(() => useLibraryFilters())

    act(() => {
      result.current.dispatch({ type: 'SET_SEARCH_QUERY', payload: 'test' })
    })

    expect(mockReplace).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(500)
    })

    expect(mockReplace).toHaveBeenCalledWith(expect.stringContaining('q=test'), expect.anything())

    vi.useRealTimers()
  })
})

describe('useLibraryFilters — search debounce', () => {
  it('should update searchInput immediately and searchQuery after 400ms', () => {
    vi.useFakeTimers()

    const { result } = renderHook(() => useLibraryFilters())

    act(() => {
      result.current.handleSearchChange('test')
    })

    // searchInput updates immediately (SET_SEARCH_INPUT is synchronous)
    expect(result.current.state.searchInput).toBe('test')
    // searchQuery is still empty — the 400ms debounce has not fired
    expect(result.current.state.searchQuery).toBe('')

    act(() => {
      vi.advanceTimersByTime(400)
    })

    // After the debounce fires, searchQuery catches up
    expect(result.current.state.searchQuery).toBe('test')

    vi.useRealTimers()
  })
})
