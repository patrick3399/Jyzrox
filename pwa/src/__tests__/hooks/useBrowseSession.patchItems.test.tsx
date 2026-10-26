import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useBrowseSession } from '@/lib/browse/useBrowseSession'
import { publishBrowseListPatch } from '@/lib/browse/listPatches'
import {
  createBrowseSnapshotStore,
  snapshotStorageKey,
  type BrowseSnapshotScope,
} from '@/lib/browse/snapshotStore'

/**
 * Item patches on a browse session. A user's own change to an item (a
 * bookmark, a favourite) is applied in place to the live buffer and to the
 * saved snapshots. Before, the only tool was refresh(): one request per loaded
 * page on rate-limited sources, aborted when the page unmounted, so the saved
 * snapshot kept the old state.
 */

type Identity = { surface: 'search'; query: string }
type Item = { id: number; label: string }
type Cursor = string
type Page = { items: Item[]; cursor: Cursor | null; hasMore: boolean; total: number | null }
type FetchPage = (identity: Identity, cursor: Cursor | null, signal: AbortSignal) => Promise<Page>

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
const KEY = 'search:A'
const IDENTITY: Identity = { surface: 'search', query: 'A' }

const relabel = (id: number, label: string) => ({
  updateItem: (item: Item) => (item.id === id ? { ...item, label } : item),
})

function seed(storage: Storage, pages: Item[][]) {
  createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(KEY, {
    pages,
    cursor: 'tail',
    hasMore: true,
    total: 20,
    anchor: null,
    layout: null,
  })
}

function savedPages(storage: Storage) {
  return createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).load(KEY)?.pages
}

function renderSession(storage: Storage, fetchPage: FetchPage, ready = true) {
  return renderHook(() =>
    useBrowseSession<Item, Cursor, Identity>({
      identity: IDENTITY,
      identityKey: KEY,
      adapter: { getItemId: (item) => item.id, fetchPage },
      scope,
      storage,
      ready,
    }),
  )
}

describe('useBrowseSession item patches', () => {
  it('patches the live buffer and the saved snapshot without a request', async () => {
    const storage = new MemoryStorage()
    seed(storage, [[{ id: 1, label: 'one' }], [{ id: 2, label: 'two' }]])
    const fetchPage = vi.fn<FetchPage>()
    const { result } = renderSession(storage, fetchPage)
    await waitFor(() => expect(result.current.state.items).toHaveLength(2))

    act(() => result.current.patchItems(relabel(2, 'patched')))

    expect(result.current.state.items).toEqual([
      { id: 1, label: 'one' },
      { id: 2, label: 'patched' },
    ])
    expect(savedPages(storage)).toEqual([[{ id: 1, label: 'one' }], [{ id: 2, label: 'patched' }]])
    expect(fetchPage).not.toHaveBeenCalled()
  })

  it('still patches the saved snapshot when the change settles after the list unmounted', async () => {
    const storage = new MemoryStorage()
    seed(storage, [[{ id: 1, label: 'one' }]])
    const { result, unmount } = renderSession(storage, vi.fn<FetchPage>())
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))
    const { patchItems } = result.current
    unmount()

    patchItems(relabel(1, 'settled late'))

    expect(savedPages(storage)).toEqual([[{ id: 1, label: 'settled late' }]])
  })

  it('applies a patch another page published for its partition', async () => {
    const storage = new MemoryStorage()
    seed(storage, [[{ id: 1, label: 'one' }]])
    const { result } = renderSession(storage, vi.fn<FetchPage>())
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    act(() => publishBrowseListPatch({ storage, scope, patch: relabel(1, 'from detail page') }))

    expect(result.current.state.items).toEqual([{ id: 1, label: 'from detail page' }])
  })

  it('ignores a patch published for another browser tab partition', async () => {
    const storage = new MemoryStorage()
    seed(storage, [[{ id: 1, label: 'one' }]])
    const { result } = renderSession(storage, vi.fn<FetchPage>())
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    act(() =>
      publishBrowseListPatch({
        storage,
        scope: { ...scope, tabId: 'tab-b' },
        patch: relabel(1, 'other tab'),
      }),
    )

    expect(result.current.state.items).toEqual([{ id: 1, label: 'one' }])
    expect(savedPages(storage)).toEqual([[{ id: 1, label: 'one' }]])
  })

  it('replays a patch that arrived during a refresh onto the refreshed page fetched before it', async () => {
    const storage = new MemoryStorage()
    seed(storage, [[{ id: 1, label: 'one' }]])
    let respond!: (page: Page) => void
    const fetchPage = vi.fn<FetchPage>(() => new Promise<Page>((resolve) => (respond = resolve)))
    const { result } = renderSession(storage, fetchPage)
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    let refreshing!: Promise<void>
    act(() => {
      refreshing = result.current.refresh()
    })
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1))
    act(() => result.current.patchItems(relabel(1, 'patched')))
    await act(async () => {
      respond({
        items: [{ id: 1, label: 'stale server copy' }],
        cursor: null,
        hasMore: false,
        total: 1,
      })
      await refreshing
    })

    expect(result.current.state.status).toBe('idle')
    expect(result.current.state.items).toEqual([{ id: 1, label: 'patched' }])
  })

  it('refreshes a deep list from its first page only when asked for depth "first"', async () => {
    const storage = new MemoryStorage()
    seed(storage, [
      [{ id: 1, label: 'one' }],
      [{ id: 2, label: 'two' }],
      [{ id: 3, label: 'three' }],
    ])
    const fetchPage = vi.fn<FetchPage>(async () => ({
      items: [{ id: 9, label: 'fresh' }],
      cursor: 'next',
      hasMore: true,
      total: 30,
    }))
    const { result } = renderSession(storage, fetchPage)
    await waitFor(() => expect(result.current.state.items).toHaveLength(3))

    await act(async () => result.current.refresh({ depth: 'first' }))

    expect(fetchPage).toHaveBeenCalledTimes(1)
    expect(fetchPage).toHaveBeenCalledWith(IDENTITY, null, expect.any(AbortSignal))
    expect(result.current.state).toMatchObject({
      pages: [[{ id: 9, label: 'fresh' }]],
      cursor: 'next',
      hasMore: true,
      total: 30,
    })
  })

  it('does nothing while the browse scope is not ready', () => {
    const storage = new MemoryStorage()
    seed(storage, [[{ id: 1, label: 'one' }]])
    const before = storage.getItem(snapshotStorageKey(scope))
    const { result } = renderSession(storage, vi.fn<FetchPage>(), false)

    act(() => result.current.patchItems(relabel(1, 'too early')))

    expect(storage.getItem(snapshotStorageKey(scope))).toBe(before)
  })
})
