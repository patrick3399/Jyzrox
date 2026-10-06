import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const galleries = vi.hoisted(() => vi.fn())
const wsState = vi.hoisted(() => ({
  lastJobUpdate: null as null | { job_id: string; status: string; progress: null },
  connected: true,
}))

vi.mock('@/lib/api', () => ({
  api: { search: { galleries } },
}))

vi.mock('@/lib/ws', () => ({
  useWsJobs: () => ({ lastJobUpdate: wsState.lastJobUpdate }),
  useWsConnection: () => ({ connected: wsState.connected }),
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

const item = (id: number, overrides: Record<string, unknown> = {}) => ({
  id,
  title: `gallery-${id}`,
  title_jpn: null,
  source: 'ehentai',
  source_id: String(id),
  source_url: null,
  artist_id: null,
  import_mode: null,
  category: null,
  language: null,
  pages: 10,
  rating: 0,
  favorited: false,
  is_favorited: false,
  my_rating: null,
  in_reading_list: false,
  cover_thumb: null,
  uploader: null,
  download_status: 'complete',
  added_at: null,
  posted_at: null,
  tags: [],
  tags_array: [],
  ...overrides,
})

type Response = {
  items: ReturnType<typeof item>[]
  next_cursor?: string
  has_next: boolean
  total?: number
}

const firstPage = (ids: number[], total: number, next = true): Response => ({
  items: ids.map((id) => item(id)),
  next_cursor: next ? 'cursor-2' : undefined,
  has_next: next,
  total,
})

const secondPage = (ids: number[]): Response => ({
  items: ids.map((id) => item(id)),
  next_cursor: undefined,
  has_next: false,
})

function mount(storage: Storage) {
  return renderHook(() =>
    useLibraryBrowseSession({
      query: '',
      enabled: true,
      userId: 'member-42',
      tabId: 'tab-a',
      storage,
    }),
  )
}

const ids = (view: ReturnType<typeof mount>) =>
  view.result.current.state.items.map((gallery) => gallery.id)

/** Load two pages, then unmount so the session persists a two-page snapshot. Item ids must be positive. */
async function leaveTwoPageSnapshot(storage: Storage) {
  galleries.mockResolvedValueOnce(firstPage([4, 3], 4)).mockResolvedValueOnce(secondPage([2, 1]))
  const view = mount(storage)
  await waitFor(() => expect(ids(view)).toEqual([4, 3]))
  await act(async () => view.result.current.loadMore())
  expect(ids(view)).toEqual([4, 3, 2, 1])
  view.unmount()
  galleries.mockClear()
}

function setVisibility(state: 'hidden' | 'visible') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  galleries.mockReset()
  wsState.lastJobUpdate = null
  wsState.connected = true
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
})

describe('useLibraryBrowseSession revalidation without a live job event', () => {
  it('refreshes a restored snapshot at its loaded depth when the first page changed while unmounted', async () => {
    const storage = new MemoryStorage()
    await leaveTwoPageSnapshot(storage)
    // A download finished while Library was unmounted: no job event is replayed.
    galleries.mockImplementation(async (_q: string, opts: { cursor?: string }) =>
      opts.cursor ? secondPage([3, 2, 1]) : firstPage([5, 4], 5),
    )

    const view = mount(storage)

    await waitFor(() => expect(ids(view)).toEqual([5, 4, 3, 2, 1]))
    expect(view.result.current.state.status).toBe('idle')
  })

  it('does not refetch the loaded depth when the restored first page is unchanged', async () => {
    const storage = new MemoryStorage()
    await leaveTwoPageSnapshot(storage)
    galleries.mockResolvedValue(firstPage([4, 3], 4))

    const view = mount(storage)

    await waitFor(() => expect(galleries).toHaveBeenCalledOnce())
    await act(async () => {
      await Promise.resolve()
    })
    expect(galleries).toHaveBeenCalledOnce()
    expect(galleries).toHaveBeenCalledWith(
      '',
      { cursor: undefined, limit: 24, sort: 'added_at' },
      { signal: expect.any(AbortSignal) },
    )
    expect(ids(view)).toEqual([4, 3, 2, 1])
    expect(view.result.current.state.status).toBe('idle')
  })

  it('keeps the restored snapshot and idle status when the revalidation probe fails', async () => {
    const storage = new MemoryStorage()
    await leaveTwoPageSnapshot(storage)
    galleries.mockRejectedValue(new Error('offline'))

    const view = mount(storage)

    await waitFor(() => expect(galleries).toHaveBeenCalledOnce())
    await act(async () => {
      await Promise.resolve()
    })
    expect(ids(view)).toEqual([4, 3, 2, 1])
    expect(view.result.current.state).toMatchObject({ status: 'idle', error: null })
  })

  it('refreshes when an in-place change such as a late cover thumbnail reaches the first page', async () => {
    const storage = new MemoryStorage()
    galleries.mockResolvedValueOnce(firstPage([3, 2], 2, false))
    const first = mount(storage)
    await waitFor(() => expect(ids(first)).toEqual([3, 2]))
    first.unmount()
    galleries.mockReset()
    galleries.mockResolvedValue({
      items: [item(3, { cover_thumb: '/thumbs/3.webp' }), item(2)],
      has_next: false,
      total: 2,
    })

    const view = mount(storage)

    await waitFor(() =>
      expect(view.result.current.state.items[0].cover_thumb).toBe('/thumbs/3.webp'),
    )
  })

  it('revalidates when the websocket reconnects after missing job events', async () => {
    const storage = new MemoryStorage()
    galleries.mockResolvedValueOnce(firstPage([3, 2], 2, false))
    const view = mount(storage)
    await waitFor(() => expect(ids(view)).toEqual([3, 2]))
    galleries.mockResolvedValue(firstPage([4, 3, 2], 3, false))

    wsState.connected = false
    view.rerender()
    expect(galleries).toHaveBeenCalledOnce()
    wsState.connected = true
    view.rerender()

    await waitFor(() => expect(ids(view)).toEqual([4, 3, 2]))
  })

  it('does not revalidate on the first websocket connection after a fresh load', async () => {
    const storage = new MemoryStorage()
    wsState.connected = false
    galleries.mockResolvedValue(firstPage([3, 2], 2, false))
    const view = mount(storage)
    await waitFor(() => expect(ids(view)).toEqual([3, 2]))

    wsState.connected = true
    view.rerender()
    await act(async () => {
      await Promise.resolve()
    })

    expect(galleries).toHaveBeenCalledOnce()
  })

  it('revalidates when the page becomes visible again after being backgrounded', async () => {
    const storage = new MemoryStorage()
    galleries.mockResolvedValueOnce(firstPage([3, 2], 2, false))
    const view = mount(storage)
    await waitFor(() => expect(ids(view)).toEqual([3, 2]))
    galleries.mockResolvedValue(firstPage([4, 3, 2], 3, false))

    act(() => setVisibility('hidden'))
    expect(galleries).toHaveBeenCalledOnce()
    act(() => setVisibility('visible'))

    await waitFor(() => expect(ids(view)).toEqual([4, 3, 2]))
  })

  it('stops listening for visibility changes after unmount', async () => {
    const storage = new MemoryStorage()
    galleries.mockResolvedValue(firstPage([3, 2], 2, false))
    const view = mount(storage)
    await waitFor(() => expect(ids(view)).toEqual([3, 2]))
    view.unmount()
    galleries.mockClear()

    act(() => setVisibility('hidden'))
    act(() => setVisibility('visible'))
    await act(async () => {
      await Promise.resolve()
    })

    expect(galleries).not.toHaveBeenCalled()
  })
})
