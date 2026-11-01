import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, type Mock } from 'vitest'
import type { BrowsePageResult } from '@/lib/browse/reducer'
import { useBrowseSession } from '@/hooks/useBrowseSession'
import { createBrowseSnapshotStore, type BrowseSnapshotScope } from '@/lib/browse/snapshotStore'

/**
 * Regression (audit EH-2 / PX-10): every remount waits for the browse-tab-scope
 * claim (>= 32 ms broadcast probe) before `ready` flips true. During that window
 * the kernel published `status: 'idle'` with zero items, and a consumer's seed
 * effect could call `loadMore`, which fetched a placeholder empty page and
 * committed it. Both flashed "No results" before the snapshot hydrated on
 * back-navigation.
 */

type Item = { id: number }
type Cursor = string
type FetchPage = (
  identity: string,
  cursor: Cursor | null,
  signal: AbortSignal,
) => Promise<BrowsePageResult<Item, Cursor>>

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

const scope: BrowseSnapshotScope = {
  userId: '42',
  tabId: 'tab-a',
  sourceId: 'test',
  schemaVersion: 1,
}

const IDENTITY_KEY = 'search:A'

function render(options: {
  ready: boolean
  storage: Storage
  fetchPage: Mock<FetchPage>
  autoLoad?: boolean
}) {
  return renderHook(
    ({ ready }: { ready: boolean }) =>
      useBrowseSession<Item, Cursor, string>({
        identity: 'A',
        identityKey: IDENTITY_KEY,
        adapter: { getItemId: (item) => item.id, fetchPage: options.fetchPage },
        scope,
        storage: options.storage,
        ready,
        autoLoad: options.autoLoad,
      }),
    { initialProps: { ready: options.ready } },
  )
}

describe('useBrowseSession while the tab scope is not ready', () => {
  it('publishes loading instead of an idle empty list while ready is false', () => {
    const fetchPage = vi.fn<FetchPage>()
    const { result } = render({ ready: false, storage: new MemoryStorage(), fetchPage })

    expect(result.current.state.status).toBe('loading')
    expect(result.current.state.items).toEqual([])
    expect(fetchPage).not.toHaveBeenCalled()
  })

  it('ignores loadMore, refresh and retry while ready is false', async () => {
    const fetchPage = vi.fn<FetchPage>().mockResolvedValue({
      items: [],
      cursor: null,
      hasMore: false,
      total: 0,
    })
    const { result } = render({ ready: false, storage: new MemoryStorage(), fetchPage })

    await act(async () => {
      await result.current.loadMore()
      await result.current.refresh()
      await result.current.retry()
    })

    expect(fetchPage).not.toHaveBeenCalled()
    expect(result.current.state.status).toBe('loading')
    expect(result.current.state.items).toEqual([])
    expect(result.current.state.pages).toEqual([])
  })

  it('hydrates the stored snapshot without fetching once ready flips true', async () => {
    const storage = new MemoryStorage()
    createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(IDENTITY_KEY, {
      pages: [[{ id: 1 }, { id: 2 }]],
      cursor: 'c2',
      hasMore: true,
      total: 5,
      anchor: null,
      layout: null,
    })
    const fetchPage = vi.fn<FetchPage>()
    const { result, rerender } = render({ ready: false, storage, fetchPage })

    // A consumer's seed effect fires in the claim window.
    await act(async () => {
      await result.current.loadMore()
    })
    expect(result.current.state.items).toEqual([])
    expect(result.current.state.status).toBe('loading')

    rerender({ ready: true })

    await waitFor(() => expect(result.current.state.items).toEqual([{ id: 1 }, { id: 2 }]))
    expect(result.current.state.status).toBe('idle')
    expect(result.current.state.cursor).toBe('c2')
    expect(fetchPage).not.toHaveBeenCalled()
  })

  it('loads the first page once ready flips true with nothing stored', async () => {
    const fetchPage = vi.fn<FetchPage>().mockResolvedValue({
      items: [{ id: 7 }],
      cursor: null,
      hasMore: false,
      total: 1,
    })
    const { result, rerender } = render({ ready: false, storage: new MemoryStorage(), fetchPage })

    await act(async () => {
      await result.current.loadMore()
    })
    expect(fetchPage).not.toHaveBeenCalled()

    rerender({ ready: true })

    await waitFor(() => expect(result.current.state.items).toEqual([{ id: 7 }]))
    expect(fetchPage).toHaveBeenCalledTimes(1)
    expect(result.current.state.status).toBe('idle')
  })

  it('does not report loading for a ready session whose list is genuinely empty', async () => {
    const fetchPage = vi.fn<FetchPage>().mockResolvedValue({
      items: [],
      cursor: null,
      hasMore: false,
      total: 0,
    })
    const { result } = render({ ready: true, storage: new MemoryStorage(), fetchPage })

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(result.current.state.status).toBe('idle'))
    expect(result.current.state.items).toEqual([])
  })
})
