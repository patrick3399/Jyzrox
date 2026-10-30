import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const navigation = vi.hoisted(() => ({
  search: '',
  replace: vi.fn(),
  router: undefined as unknown as { replace: ReturnType<typeof vi.fn> },
}))
navigation.router = { replace: navigation.replace }

vi.mock('next/navigation', () => ({
  useRouter: () => navigation.router,
  useSearchParams: () => new URLSearchParams(navigation.search),
}))

import { useUnifiedSearch } from '@/hooks/useUnifiedSearch'

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  navigation.search = ''
  navigation.replace.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useUnifiedSearch text/filter split', () => {
  it('test_set_filter_does_not_write_filter_tokens_into_input', () => {
    navigation.search = 'q=rem'
    const { result } = renderHook(() => useUnifiedSearch())

    act(() => result.current.setFilter('source', 'pixiv'))

    expect(result.current.inputValue).toBe('rem')
    expect(result.current.rawQuery).toBe('rem source:pixiv')
  })

  it('test_typing_text_keeps_active_filters_in_raw_query', () => {
    navigation.search = 'q=rem+source%3Apixiv+sort%3Arating'
    const { result } = renderHook(() => useUnifiedSearch())

    act(() => result.current.handleInputChange('ram'))
    // Not committed (and input not normalised) before the debounce fires.
    expect(result.current.inputValue).toBe('ram')
    advance(300)

    expect(result.current.rawQuery).toBe('ram source:pixiv sort:rating')
    expect(result.current.inputValue).toBe('ram')
  })

  it('test_commit_moves_typed_filter_token_out_of_input_into_query', () => {
    const { result } = renderHook(() => useUnifiedSearch())

    act(() => result.current.commitSearch('rem source:pixiv'))

    expect(result.current.rawQuery).toBe('rem source:pixiv')
    expect(result.current.inputValue).toBe('rem')
    expect(result.current.parsed.source).toBe('pixiv')
  })

  it('test_clear_search_clears_text_but_keeps_filters', () => {
    navigation.search = 'q=rem+source%3Apixiv'
    const { result } = renderHook(() => useUnifiedSearch())

    act(() => result.current.clearSearch())

    expect(result.current.inputValue).toBe('')
    expect(result.current.rawQuery).toBe('source:pixiv')
    advance(500)
    expect(navigation.replace).toHaveBeenCalledWith('/library?q=source%3Apixiv', { scroll: false })
  })

  it('test_clear_filters_keeps_text', () => {
    navigation.search = 'q=rem+source%3Apixiv+favorited%3Atrue'
    const { result } = renderHook(() => useUnifiedSearch())

    act(() => result.current.clearFilters())

    expect(result.current.rawQuery).toBe('rem')
    expect(result.current.inputValue).toBe('rem')
    advance(500)
    expect(navigation.replace).toHaveBeenCalledWith('/library?q=rem', { scroll: false })
  })

  it('test_incoming_url_query_shows_only_text_in_input', () => {
    navigation.search = 'q=rem+source%3Apixiv'
    const view = renderHook(() => useUnifiedSearch())
    expect(view.result.current.inputValue).toBe('rem')

    navigation.search = 'q=ram+rating%3A%3E%3D4'
    view.rerender()

    expect(view.result.current.rawQuery).toBe('ram rating:>=4')
    expect(view.result.current.inputValue).toBe('ram')
  })

  it('test_clear_filters_cancels_pending_typed_text_debounce_without_restoring_filters', () => {
    navigation.search = 'q=source%3Apixiv'
    const { result } = renderHook(() => useUnifiedSearch())

    act(() => result.current.clearFilters())
    advance(500)

    expect(result.current.rawQuery).toBe('')
  })
})
