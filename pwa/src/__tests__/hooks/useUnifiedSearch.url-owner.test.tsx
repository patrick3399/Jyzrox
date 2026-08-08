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

describe('useUnifiedSearch URL ownership', () => {
  it('updates rawQuery when browser back or forward changes searchParams after mount', () => {
    navigation.search = 'q=artist%3Afirst'
    const view = renderHook(() => useUnifiedSearch())
    expect(view.result.current.rawQuery).toBe('artist:first')

    navigation.search = 'q=artist%3Asecond'
    view.rerender()

    expect(view.result.current.rawQuery).toBe('artist:second')
    expect(view.result.current.inputValue).toBe('artist:second')
  })

  it('cancels an old outbound debounce when a newer URL identity arrives', () => {
    navigation.search = 'q=initial'
    const view = renderHook(() => useUnifiedSearch())

    act(() => view.result.current.commitSearch('stale-local'))
    navigation.search = 'q=fresh-history'
    view.rerender()
    advance(500)

    expect(view.result.current.rawQuery).toBe('fresh-history')
    expect(navigation.replace).not.toHaveBeenCalledWith(
      expect.stringContaining('stale-local'),
      expect.anything(),
    )
  })

  it('performs exactly one replace for one user-committed query change', () => {
    navigation.search = 'q=initial'
    const { result } = renderHook(() => useUnifiedSearch())
    advance(500)
    navigation.replace.mockClear()

    act(() => result.current.commitSearch('artist:next'))
    advance(499)
    expect(navigation.replace).not.toHaveBeenCalled()
    advance(1)

    expect(navigation.replace).toHaveBeenCalledOnce()
    expect(navigation.replace).toHaveBeenCalledWith('/library?q=artist%3Anext', {
      scroll: false,
    })
  })

  it('does not replace the URL for a canonically equivalent query', () => {
    navigation.search = 'q=artist%3Aa+artist%3Az'
    const { result } = renderHook(() => useUnifiedSearch())
    advance(500)
    navigation.replace.mockClear()

    act(() => result.current.commitSearch('artist:z artist:a artist:a'))
    advance(500)

    expect(navigation.replace).not.toHaveBeenCalled()
  })
})
