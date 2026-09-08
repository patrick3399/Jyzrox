import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useReaderState } from '@/components/Reader/hooks'

describe('useReaderState grid overview', () => {
  it('starts with the grid closed', () => {
    const { result } = renderHook(() => useReaderState(1, 10, 'ehentai', '123'))
    expect(result.current.state.isGridOpen).toBe(false)
  })

  it('showGrid opens it and hideGrid closes it', () => {
    const { result } = renderHook(() => useReaderState(1, 10, 'ehentai', '123'))

    act(() => result.current.showGrid())
    expect(result.current.state.isGridOpen).toBe(true)

    act(() => result.current.hideGrid())
    expect(result.current.state.isGridOpen).toBe(false)
  })

  it('does not clear isGridOpen as a side effect of turning pages', () => {
    const { result } = renderHook(() => useReaderState(1, 10, 'ehentai', '123'))

    act(() => result.current.showGrid())
    act(() => result.current.setPage(5))

    expect(result.current.state.isGridOpen).toBe(true)
    expect(result.current.state.currentPage).toBe(5)
  })
})
