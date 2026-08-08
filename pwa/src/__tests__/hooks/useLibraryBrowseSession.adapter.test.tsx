import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const galleries = vi.hoisted(() => vi.fn())
const wsState = vi.hoisted(() => ({
  lastJobUpdate: null as null | { job_id: string; status: string; progress: null },
}))

vi.mock('@/lib/api', () => ({
  api: { search: { galleries } },
}))

vi.mock('@/lib/ws', () => ({
  useWsJobs: () => wsState,
}))

import { useLibraryBrowseSession } from '@/hooks/useLibraryBrowseSession'

class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() {
    return this.values.size
  }
  clear() {
    this.values.clear()
  }
  getItem(key: string) {
    return this.values.get(key) ?? null
  }
  key(index: number) {
    return [...this.values.keys()][index] ?? null
  }
  removeItem(key: string) {
    this.values.delete(key)
  }
  setItem(key: string, value: string) {
    this.values.set(key, value)
  }
}

beforeEach(() => {
  galleries.mockReset()
  galleries.mockResolvedValue({ items: [], next_cursor: undefined, has_next: false, total: 0 })
  wsState.lastJobUpdate = null
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useLibraryBrowseSession adapter', () => {
  it('does not request Library data before the profile scope is enabled', async () => {
    const storage = new MemoryStorage()
    const view = renderHook(
      ({ enabled, userId }) =>
        useLibraryBrowseSession({
          query: 'artist:a sort:rating',
          enabled,
          userId,
          tabId: 'tab-a',
          storage,
        }),
      { initialProps: { enabled: false, userId: undefined as string | undefined } },
    )

    await Promise.resolve()
    expect(galleries).not.toHaveBeenCalled()
    expect(storage.length).toBe(0)

    view.rerender({ enabled: true, userId: 'member-42' })
    await waitFor(() => expect(galleries).toHaveBeenCalledOnce())
    expect(galleries).toHaveBeenCalledWith(
      'artist:a',
      { cursor: undefined, limit: 24, sort: 'rating' },
      { signal: expect.any(AbortSignal) },
    )
  })

  it('maps the search cursor response without SWR ownership', async () => {
    const storage = new MemoryStorage()
    galleries.mockResolvedValueOnce({
      items: [{ id: 7, title: 'Gallery' }],
      next_cursor: 'cursor-2',
      has_next: true,
      total: 18,
    })

    const { result } = renderHook(() =>
      useLibraryBrowseSession({
        query: 'source:pixiv',
        enabled: true,
        userId: 'member-42',
        tabId: 'tab-a',
        storage,
      }),
    )

    await waitFor(() => expect(result.current.state.cursor).toBe('cursor-2'))
    expect(result.current.state).toMatchObject({ hasMore: true, total: 18 })
    expect(result.current.state.items).toEqual([{ id: 7, title: 'Gallery' }])
  })

  it('invalidates library_scrollY only after the user scope resolves', async () => {
    const storage = new MemoryStorage()
    storage.setItem('library_scrollY', JSON.stringify({ scrollY: 900 }))
    const view = renderHook(
      ({ enabled, userId }) =>
        useLibraryBrowseSession({
          query: '',
          enabled,
          userId,
          tabId: 'tab-a',
          storage,
        }),
      { initialProps: { enabled: false, userId: undefined as string | undefined } },
    )

    expect(storage.getItem('library_scrollY')).not.toBeNull()
    view.rerender({ enabled: true, userId: 'member-42' })
    await waitFor(() => expect(galleries).toHaveBeenCalledOnce())
    expect(storage.getItem('library_scrollY')).toBeNull()
  })

  it('throttles done and partial job updates into session refreshes', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(10_000)
    const storage = new MemoryStorage()
    const view = renderHook(() =>
      useLibraryBrowseSession({
        query: '',
        enabled: true,
        userId: 'member-42',
        tabId: 'tab-a',
        storage,
      }),
    )
    await act(async () => {
      await vi.runOnlyPendingTimersAsync()
    })
    expect(galleries).toHaveBeenCalledOnce()

    wsState.lastJobUpdate = { job_id: 'done-1', status: 'done', progress: null }
    view.rerender()
    await act(async () => {
      await Promise.resolve()
    })
    expect(galleries).toHaveBeenCalledTimes(2)

    wsState.lastJobUpdate = { job_id: 'partial-2', status: 'partial', progress: null }
    view.rerender()
    await act(async () => {
      vi.advanceTimersByTime(1_999)
      await Promise.resolve()
    })
    expect(galleries).toHaveBeenCalledTimes(2)
    await act(async () => {
      vi.advanceTimersByTime(1)
      await Promise.resolve()
    })
    expect(galleries).toHaveBeenCalledTimes(3)
  })
})
