import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useBrowseSession } from '@/lib/browse/useBrowseSession'
import {
  createBrowseSnapshotStore,
  snapshotStorageKey,
  type BrowseSnapshotScope,
} from '@/lib/browse/snapshotStore'

type LibraryIdentity = { surface: 'library'; query: string }
type Gallery = { id: number; title: string }
type Page = {
  items: Gallery[]
  cursor: string | null
  hasMore: boolean
  total: number | null
}

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

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

const identity = (query: string): LibraryIdentity => ({ surface: 'library', query })
const identityKey = (query: string) => `library:${query}`
const scope = (userId = 'member-42', tabId = 'tab-a'): BrowseSnapshotScope => ({
  userId,
  tabId,
  sourceId: 'library',
  schemaVersion: 1,
})
const snapshot = (id: number, cursor: string) => ({
  pages: [[{ id, title: `gallery-${id}` }]],
  cursor,
  hasMore: true,
  total: 12,
  anchor: { itemId: id, offset: 8, scrollY: id * 100 },
  layout: { columns: 4, width: 1200, mode: 'grid' },
})

describe('Library browse-session state contract', () => {
  it('keeps A and B pages, cursors, and anchors isolated during A to B to A navigation', async () => {
    const storage = new MemoryStorage()
    const store = createBrowseSnapshotStore<Gallery, string>({ storage, scope: scope() })
    store.save(identityKey('A'), snapshot(1, 'cursor-a'))
    store.save(identityKey('B'), snapshot(2, 'cursor-b'))
    const fetchPage = vi.fn()
    const view = renderHook(
      ({ query }) =>
        useBrowseSession<Gallery, string, LibraryIdentity>({
          identity: identity(query),
          identityKey: identityKey(query),
          adapter: { getItemId: (gallery) => gallery.id, fetchPage },
          scope: scope(),
          storage,
        }),
      { initialProps: { query: 'A' } },
    )

    await waitFor(() => expect(view.result.current.state.cursor).toBe('cursor-a'))
    expect(view.result.current.state.items.map((gallery) => gallery.id)).toEqual([1])
    expect(view.result.current.restoreInstruction).toMatchObject({
      identityKey: identityKey('A'),
      target: { kind: 'view', view: { anchor: { itemId: 1 } } },
    })

    view.rerender({ query: 'B' })
    await waitFor(() => expect(view.result.current.state.cursor).toBe('cursor-b'))
    expect(view.result.current.state.items.map((gallery) => gallery.id)).toEqual([2])
    expect(view.result.current.restoreInstruction).toMatchObject({
      identityKey: identityKey('B'),
      target: { kind: 'view', view: { anchor: { itemId: 2 } } },
    })

    view.rerender({ query: 'A' })
    await waitFor(() => expect(view.result.current.state.cursor).toBe('cursor-a'))
    expect(view.result.current.state.items.map((gallery) => gallery.id)).toEqual([1])
    expect(view.result.current.restoreInstruction).toMatchObject({
      identityKey: identityKey('A'),
      target: { kind: 'view', view: { anchor: { itemId: 1 } } },
    })
    expect(fetchPage).not.toHaveBeenCalled()
  })

  it('partitions Library snapshots by both authenticated user and browser tab', () => {
    const storage = new MemoryStorage()
    const owner = createBrowseSnapshotStore<Gallery, string>({ storage, scope: scope() })
    owner.save(identityKey('same-query'), snapshot(7, 'owner-cursor'))

    const anotherUser = createBrowseSnapshotStore<Gallery, string>({
      storage,
      scope: scope('member-99', 'tab-a'),
    })
    const anotherTab = createBrowseSnapshotStore<Gallery, string>({
      storage,
      scope: scope('member-42', 'tab-b'),
    })

    expect(owner.restore(identityKey('same-query')).kind).toBe('snapshot')
    expect(anotherUser.restore(identityKey('same-query')).kind).toBe('missing')
    expect(anotherTab.restore(identityKey('same-query')).kind).toBe('missing')
    expect(snapshotStorageKey(scope())).not.toBe(snapshotStorageKey(scope('member-99', 'tab-a')))
    expect(snapshotStorageKey(scope())).not.toBe(snapshotStorageKey(scope('member-42', 'tab-b')))
  })

  it('aborts superseded requests and ignores stale A completion after A to B to A', async () => {
    const calls: Array<{
      identity: LibraryIdentity
      signal: AbortSignal
      request: ReturnType<typeof deferred<Page>>
    }> = []
    const fetchPage = vi.fn(
      (nextIdentity: LibraryIdentity, _cursor: string | null, signal: AbortSignal) => {
        const request = deferred<Page>()
        calls.push({ identity: nextIdentity, signal, request })
        return request.promise
      },
    )
    const storage = new MemoryStorage()
    const view = renderHook(
      ({ query }) =>
        useBrowseSession<Gallery, string, LibraryIdentity>({
          identity: identity(query),
          identityKey: identityKey(query),
          adapter: { getItemId: (gallery) => gallery.id, fetchPage },
          scope: scope(),
          storage,
        }),
      { initialProps: { query: 'A' } },
    )

    await waitFor(() => expect(calls).toHaveLength(1))
    view.rerender({ query: 'B' })
    await waitFor(() => expect(calls).toHaveLength(2))
    view.rerender({ query: 'A' })
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(calls[0].signal.aborted).toBe(true)
    expect(calls[1].signal.aborted).toBe(true)

    await act(async () => {
      calls[0].request.resolve({
        items: [{ id: 1, title: 'stale A' }],
        cursor: 'stale',
        hasMore: true,
        total: 9,
      })
      calls[2].request.resolve({
        items: [{ id: 3, title: 'current A' }],
        cursor: 'current',
        hasMore: true,
        total: 9,
      })
      await Promise.resolve()
    })

    await waitFor(() => expect(view.result.current.state.cursor).toBe('current'))
    expect(view.result.current.state.items).toEqual([{ id: 3, title: 'current A' }])
  })

  it('allows load-more to retry after an append error without losing the cursor', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({
        items: [{ id: 1, title: 'first page' }],
        cursor: 'cursor-1',
        hasMore: true,
        total: 2,
      })
      .mockRejectedValueOnce(new Error('temporary append failure'))
      .mockResolvedValueOnce({
        items: [{ id: 2, title: 'second page' }],
        cursor: null,
        hasMore: false,
        total: 2,
      })
    const storage = new MemoryStorage()
    const { result } = renderHook(() =>
      useBrowseSession<Gallery, string, LibraryIdentity>({
        identity: identity('paged'),
        identityKey: identityKey('paged'),
        adapter: { getItemId: (gallery) => gallery.id, fetchPage },
        scope: scope(),
        storage,
      }),
    )

    await waitFor(() => expect(result.current.state.cursor).toBe('cursor-1'))
    await act(async () => result.current.loadMore())
    expect(result.current.state).toMatchObject({
      status: 'error',
      cursor: 'cursor-1',
      hasMore: true,
    })
    expect(result.current.state.items.map((gallery) => gallery.id)).toEqual([1])

    await act(async () => result.current.loadMore())
    expect(fetchPage).toHaveBeenNthCalledWith(
      3,
      identity('paged'),
      'cursor-1',
      expect.any(AbortSignal),
    )
    expect(result.current.state.items.map((gallery) => gallery.id)).toEqual([1, 2])
    expect(result.current.state).toMatchObject({ status: 'idle', hasMore: false })
  })
})
