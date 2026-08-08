import { act, render, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useBrowseSession } from '@/lib/browse/useBrowseSession'
import type { BrowseSessionResult } from '@/lib/browse/useBrowseSession'
import { createBrowseSnapshotStore, type BrowseSnapshotScope } from '@/lib/browse/snapshotStore'

type Identity = { surface: 'search'; query: string }
type Item = { id: number; label: string }
type Cursor = string
type PageResponse = {
  items: Item[]
  cursor: Cursor | null
  hasMore: boolean
  total: number | null
}
type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (error: unknown) => void
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

const scope: BrowseSnapshotScope = {
  userId: '42',
  tabId: 'tab-a',
  sourceId: 'test',
  schemaVersion: 1,
}

const identity = (query: string): Identity => ({ surface: 'search', query })
const key = (query: string) => `search:${query}`

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

function refreshSession(
  session: BrowseSessionResult<Item, Cursor>,
): Promise<void> {
  return (session as BrowseSessionResult<Item, Cursor> & { refresh: () => Promise<void> }).refresh()
}

function retrySession(session: BrowseSessionResult<Item, Cursor>): Promise<void> {
  return (session as BrowseSessionResult<Item, Cursor> & { retry: () => Promise<void> }).retry()
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useBrowseSession', () => {
  it('atomically hydrates the exact identity from its scoped snapshot without fetching', async () => {
    const storage = new MemoryStorage()
    const store = createBrowseSnapshotStore<Item, Cursor>({ storage, scope })
    const saved = {
      pages: [[{ id: 1, label: 'one' }], [{ id: 2, label: 'two' }]],
      cursor: 'cursor-2',
      hasMore: true,
      total: 9,
      anchor: { itemId: 2, offset: 12, scrollY: 700 },
      layout: { columns: 4, width: 1200, mode: 'grid' },
    }
    store.save(key('A'), saved)
    const fetchPage = vi.fn()

    const { result } = renderHook(() =>
      useBrowseSession<Item, Cursor, Identity>({
        identity: identity('A'),
        identityKey: key('A'),
        adapter: { getItemId: (item) => item.id, fetchPage },
        scope,
        storage,
      }),
    )

    await waitFor(() => expect(result.current.state.items).toHaveLength(2))
    expect(result.current.state).toMatchObject({
      pages: saved.pages,
      items: saved.pages.flat(),
      cursor: 'cursor-2',
      hasMore: true,
      total: 9,
    })
    expect(fetchPage).not.toHaveBeenCalled()
  })

  it('aborts A and B and rejects stale A success across an A to B to A round trip', async () => {
    const calls: Array<{
      identity: Identity
      signal: AbortSignal
      request: ReturnType<
        typeof deferred<{
          items: Item[]
          cursor: Cursor | null
          hasMore: boolean
          total: number | null
        }>
      >
    }> = []
    const fetchPage = vi.fn(
      (nextIdentity: Identity, _cursor: Cursor | null, signal: AbortSignal) => {
        const request = deferred<{
          items: Item[]
          cursor: Cursor | null
          hasMore: boolean
          total: number | null
        }>()
        calls.push({ identity: nextIdentity, signal, request })
        return request.promise
      },
    )
    const storage = new MemoryStorage()
    const view = renderHook(
      ({ query }) =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity(query),
          identityKey: key(query),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      { initialProps: { query: 'A' } },
    )

    await waitFor(() => expect(calls).toHaveLength(1))
    view.rerender({ query: 'B' })
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[0].signal.aborted).toBe(true)
    view.rerender({ query: 'A' })
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(calls[1].signal.aborted).toBe(true)

    await act(async () => {
      calls[0].request.resolve({
        items: [{ id: 1, label: 'stale A' }],
        cursor: null,
        hasMore: false,
        total: 1,
      })
      calls[2].request.resolve({
        items: [{ id: 3, label: 'current A' }],
        cursor: null,
        hasMore: false,
        total: 1,
      })
      await Promise.resolve()
    })

    await waitFor(() => expect(view.result.current.state.items[0]?.label).toBe('current A'))
    expect(view.result.current.state.items).toEqual([{ id: 3, label: 'current A' }])
  })

  it('accepts an immediately resolved fetch for the new identity before reducer state commits', async () => {
    const fetchPage = vi.fn(async (nextIdentity: Identity) => ({
      items: [{ id: nextIdentity.query === 'A' ? 1 : 2, label: nextIdentity.query }],
      cursor: null,
      hasMore: false,
      total: 1,
    }))
    const storage = new MemoryStorage()
    const view = renderHook(
      ({ query }) =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity(query),
          identityKey: key(query),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      { initialProps: { query: 'A' } },
    )
    await waitFor(() => expect(view.result.current.state.items[0]?.label).toBe('A'))

    view.rerender({ query: 'B' })

    await waitFor(() => expect(view.result.current.state.items[0]?.label).toBe('B'))
    expect(view.result.current.state.identityKey).toBe(key('B'))
    expect(fetchPage).toHaveBeenLastCalledWith(identity('B'), null, expect.any(AbortSignal))
  })

  it('does not surface a stale aborted error after returning to the same identity', async () => {
    const requests: Deferred<PageResponse>[] = [
      deferred<PageResponse>(),
      deferred<PageResponse>(),
      deferred<PageResponse>(),
    ]
    let call = 0
    const fetchPage = vi.fn(() => requests[call++].promise)
    const storage = new MemoryStorage()
    const view = renderHook(
      ({ query }) =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity(query),
          identityKey: key(query),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      { initialProps: { query: 'A' } },
    )

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1))
    view.rerender({ query: 'B' })
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(2))
    view.rerender({ query: 'A' })
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(3))

    await act(async () => {
      requests[0].reject(new Error('stale A failure'))
      requests[2].resolve({
        items: [{ id: 3, label: 'current A' }],
        cursor: null,
        hasMore: false,
        total: 1,
      })
      await Promise.resolve()
    })

    await waitFor(() => expect(view.result.current.state.status).toBe('idle'))
    expect(view.result.current.state.error).toBeNull()
    expect(view.result.current.state.items).toEqual([{ id: 3, label: 'current A' }])
  })

  it('loadMore fetches from the current cursor and appends the next page', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({
        items: [{ id: 1, label: 'one' }],
        cursor: 'cursor-1',
        hasMore: true,
        total: 2,
      })
      .mockResolvedValueOnce({
        items: [{ id: 2, label: 'two' }],
        cursor: null,
        hasMore: false,
        total: 2,
      })
    const currentIdentity = identity('paged')
    const storage = new MemoryStorage()
    const { result } = renderHook(() =>
      useBrowseSession<Item, Cursor, Identity>({
        identity: currentIdentity,
        identityKey: key('paged'),
        adapter: { getItemId: (item) => item.id, fetchPage },
        scope,
        storage,
      }),
    )

    await waitFor(() => expect(result.current.state.cursor).toBe('cursor-1'))
    await act(async () => {
      await result.current.loadMore()
    })

    expect(fetchPage).toHaveBeenNthCalledWith(
      2,
      currentIdentity,
      'cursor-1',
      expect.any(AbortSignal),
    )
    expect(result.current.state.items).toEqual([
      { id: 1, label: 'one' },
      { id: 2, label: 'two' },
    ])
    expect(result.current.state.hasMore).toBe(false)
  })

  it('checkpoints a successful empty terminal page instead of losing the identity', async () => {
    const storage = new MemoryStorage()
    const fetchPage = vi.fn().mockResolvedValue({
      items: [],
      cursor: null,
      hasMore: false,
      total: 0,
    })
    const { result } = renderHook(() =>
      useBrowseSession<Item, Cursor, Identity>({
        identity: identity('empty'),
        identityKey: key('empty'),
        adapter: { getItemId: (item) => item.id, fetchPage },
        scope,
        storage,
      }),
    )

    await waitFor(() => expect(result.current.state.hasMore).toBe(false))
    expect(result.current.checkpoint({ anchor: null, layout: null })).toBe(true)

    const stored = createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).load(key('empty'))
    expect(stored).toMatchObject({ pages: [[]], cursor: null, hasMore: false, total: 0 })
  })

  it('surfaces an expired terminal marker for a missing non-replayable identity', async () => {
    const now = vi.spyOn(Date, 'now')
    now.mockReturnValue(100)
    const storage = new MemoryStorage()
    const store = createBrowseSnapshotStore<Item, Cursor>({ storage, scope })
    store.save(
      key('upload-result'),
      {
        pages: [[{ id: 7, label: 'temporary result' }]],
        cursor: null,
        hasMore: false,
        total: 1,
        anchor: null,
        layout: null,
      },
      { replayable: false, ttlMs: 10 },
    )
    now.mockReturnValue(111)
    const fetchPage = vi.fn()

    const { result } = renderHook(() =>
      useBrowseSession<Item, Cursor, Identity>({
        identity: identity('upload-result'),
        identityKey: key('upload-result'),
        adapter: { getItemId: (item) => item.id, fetchPage },
        scope,
        storage,
      }),
    )

    await waitFor(() =>
      expect(result.current.state.terminal).toEqual({ kind: 'expired', replayable: false }),
    )
    expect(fetchPage).not.toHaveBeenCalled()
  })

  describe('refresh', () => {
    it('revalidates the loaded depth before replacing a deep buffer and preserves its valid anchor', async () => {
      const storage = new MemoryStorage()
      const anchor = { itemId: 2, offset: 16, scrollY: 900 }
      createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(key('deep-refresh'), {
        pages: [[{ id: 1, label: 'old one' }], [{ id: 2, label: 'old two' }]],
        cursor: 'old-tail',
        hasMore: true,
        total: 8,
        anchor,
        layout: { columns: 4, width: 1200, mode: 'grid' },
      })
      const fetchPage = vi
        .fn()
        .mockResolvedValueOnce({
          items: [{ id: 1, label: 'fresh one' }],
          cursor: 'fresh-page-2',
          hasMore: true,
          total: 8,
        })
        .mockResolvedValueOnce({
          items: [{ id: 2, label: 'fresh two' }],
          cursor: 'fresh-tail',
          hasMore: true,
          total: 8,
        })
      const view = renderHook(() =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity('deep-refresh'),
          identityKey: key('deep-refresh'),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      )
      await waitFor(() => expect(view.result.current.state.items).toHaveLength(2))

      await act(async () => refreshSession(view.result.current))

      expect(fetchPage).toHaveBeenNthCalledWith(
        1,
        identity('deep-refresh'),
        null,
        expect.any(AbortSignal),
      )
      expect(fetchPage).toHaveBeenNthCalledWith(
        2,
        identity('deep-refresh'),
        'fresh-page-2',
        expect.any(AbortSignal),
      )
      expect(view.result.current.state.pages).toEqual([
        [{ id: 1, label: 'fresh one' }],
        [{ id: 2, label: 'fresh two' }],
      ])
      expect(view.result.current.restoreInstruction).toMatchObject({
        identityKey: key('deep-refresh'),
        target: { kind: 'view', view: { anchor } },
      })
    })

    it.each([
      ['missing item', { itemId: 9, offset: 16, scrollY: 900 }],
      ['pixel-only', { itemId: null, offset: 0, scrollY: 900 }],
    ])('clears a %s anchor after an atomic refresh but preserves layout', async (_label, anchor) => {
      const storage = new MemoryStorage()
      const layout = { columns: 4, width: 1200, mode: 'grid' as const }
      createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(key('anchor-refresh'), {
        pages: [[{ id: 1, label: 'old one' }]],
        cursor: null,
        hasMore: false,
        total: 1,
        anchor,
        layout,
      })
      const fetchPage = vi.fn().mockResolvedValue({
        items: [{ id: 2, label: 'fresh two' }],
        cursor: null,
        hasMore: false,
        total: 1,
      })
      const view = renderHook(() =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity('anchor-refresh'),
          identityKey: key('anchor-refresh'),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      )
      await waitFor(() => expect(view.result.current.state.items[0]?.id).toBe(1))

      await act(async () => refreshSession(view.result.current))

      expect(view.result.current.restoreInstruction).toMatchObject({
        identityKey: key('anchor-refresh'),
        target: { kind: 'view', view: { anchor: null, layout } },
      })
    })

    it('retries a failed refresh from the first page instead of appending the old tail cursor', async () => {
      const storage = new MemoryStorage()
      createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(key('refresh-mode'), {
        pages: [[{ id: 1, label: 'old one' }]],
        cursor: 'old-tail',
        hasMore: true,
        total: 8,
        anchor: null,
        layout: null,
      })
      const fetchPage = vi
        .fn()
        .mockRejectedValueOnce(new Error('refresh failed'))
        .mockResolvedValueOnce({
          items: [{ id: 1, label: 'fresh one' }],
          cursor: null,
          hasMore: false,
          total: 1,
        })
      const view = renderHook(() =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity('refresh-mode'),
          identityKey: key('refresh-mode'),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      )
      await waitFor(() => expect(view.result.current.state.items).toHaveLength(1))
      await act(async () => refreshSession(view.result.current))
      expect(view.result.current.state.status).toBe('error')

      await act(async () => retrySession(view.result.current))

      expect(fetchPage).toHaveBeenNthCalledWith(
        2,
        identity('refresh-mode'),
        null,
        expect.any(AbortSignal),
      )
    })

    it('retries a failed append with the same tail cursor', async () => {
      const storage = new MemoryStorage()
      createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(key('append-mode'), {
        pages: [[{ id: 1, label: 'old one' }]],
        cursor: 'old-tail',
        hasMore: true,
        total: 8,
        anchor: null,
        layout: null,
      })
      const fetchPage = vi
        .fn()
        .mockRejectedValueOnce(new Error('append failed'))
        .mockResolvedValueOnce({ items: [], cursor: null, hasMore: false, total: 8 })
      const view = renderHook(() =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity('append-mode'),
          identityKey: key('append-mode'),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      )
      await waitFor(() => expect(view.result.current.state.items).toHaveLength(1))
      await act(async () => view.result.current.loadMore())
      expect(view.result.current.state.status).toBe('error')

      await act(async () => retrySession(view.result.current))

      expect(fetchPage).toHaveBeenNthCalledWith(
        2,
        identity('append-mode'),
        'old-tail',
        expect.any(AbortSignal),
      )
    })

    it('aborts an older request, fetches the current identity from a null cursor, and rejects stale success', async () => {
      const storage = new MemoryStorage()
      const anchor = { itemId: 2, offset: 16, scrollY: 900 }
      createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(key('refresh'), {
        pages: [[{ id: 1, label: 'old one' }], [{ id: 2, label: 'old two' }]],
        cursor: 'old-cursor',
        hasMore: true,
        total: 8,
        anchor,
        layout: { columns: 4, width: 1200, mode: 'grid' },
      })
      const calls: Array<{
        cursor: Cursor | null
        signal: AbortSignal
        request: Deferred<PageResponse>
      }> = []
      const fetchPage = vi.fn(
        (_identity: Identity, cursor: Cursor | null, signal: AbortSignal) => {
          const request = deferred<PageResponse>()
          calls.push({ cursor, signal, request })
          return request.promise
        },
      )
      const view = renderHook(() =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity('refresh'),
          identityKey: key('refresh'),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      )
      await waitFor(() => expect(view.result.current.state.items).toHaveLength(2))

      let staleRequest!: Promise<void>
      act(() => {
        staleRequest = view.result.current.loadMore()
      })
      await waitFor(() => expect(calls).toHaveLength(1))

      let refreshRequest!: Promise<void>
      act(() => {
        refreshRequest = refreshSession(view.result.current)
      })
      await waitFor(() => expect(calls).toHaveLength(2))

      expect(calls[0].signal.aborted).toBe(true)
      expect(fetchPage).toHaveBeenNthCalledWith(
        2,
        identity('refresh'),
        null,
        expect.any(AbortSignal),
      )
      expect(view.result.current.state.status).toBe('loading')
      expect(view.result.current.state.pages).toEqual([
        [{ id: 1, label: 'old one' }],
        [{ id: 2, label: 'old two' }],
      ])
      expect(view.result.current.restoreInstruction).toMatchObject({
        identityKey: key('refresh'),
        target: { kind: 'view', view: { anchor } },
      })

      await act(async () => {
        calls[0].request.resolve({
          items: [{ id: 99, label: 'stale append' }],
          cursor: null,
          hasMore: false,
          total: 99,
        })
        calls[1].request.resolve({
          items: [{ id: 2, label: 'fresh replacement' }],
          cursor: null,
          hasMore: false,
          total: 12,
        })
        await Promise.all([staleRequest, refreshRequest])
      })

      expect(view.result.current.state).toMatchObject({
        pages: [[{ id: 2, label: 'fresh replacement' }]],
        items: [{ id: 2, label: 'fresh replacement' }],
        cursor: null,
        hasMore: false,
        total: 12,
        status: 'idle',
        error: null,
      })
      expect(view.result.current.restoreInstruction).toMatchObject({
        identityKey: key('refresh'),
        target: { kind: 'view', view: { anchor } },
      })
    })

    it('preserves the current pages on failure and permits a later refresh retry', async () => {
      const storage = new MemoryStorage()
      createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save(key('retry'), {
        pages: [[{ id: 7, label: 'keep me' }]],
        cursor: 'old-cursor',
        hasMore: true,
        total: 4,
        anchor: { itemId: 7, offset: 5, scrollY: 300 },
        layout: null,
      })
      const requests = [deferred<PageResponse>(), deferred<PageResponse>()]
      const fetchPage = vi
        .fn()
        .mockImplementationOnce(() => requests[0].promise)
        .mockImplementationOnce(() => requests[1].promise)
      const view = renderHook(() =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: identity('retry'),
          identityKey: key('retry'),
          adapter: { getItemId: (item) => item.id, fetchPage },
          scope,
          storage,
        }),
      )
      await waitFor(() => expect(view.result.current.state.items[0]?.label).toBe('keep me'))

      let failedRefresh!: Promise<void>
      act(() => {
        failedRefresh = refreshSession(view.result.current)
      })
      await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1))
      await act(async () => {
        requests[0].reject(new Error('refresh failed'))
        await failedRefresh
      })

      expect(view.result.current.state.items).toEqual([{ id: 7, label: 'keep me' }])
      expect(view.result.current.state.pages).toEqual([[{ id: 7, label: 'keep me' }]])
      expect(view.result.current.state.status).toBe('error')
      expect(view.result.current.state.error?.message).toBe('refresh failed')

      let retry!: Promise<void>
      act(() => {
        retry = refreshSession(view.result.current)
      })
      await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(2))
      expect(fetchPage).toHaveBeenNthCalledWith(
        2,
        identity('retry'),
        null,
        expect.any(AbortSignal),
      )
      await act(async () => {
        requests[1].resolve({
          items: [{ id: 8, label: 'retry succeeded' }],
          cursor: null,
          hasMore: false,
          total: 1,
        })
        await retry
      })

      expect(view.result.current.state).toMatchObject({
        pages: [[{ id: 8, label: 'retry succeeded' }]],
        items: [{ id: 8, label: 'retry succeeded' }],
        cursor: null,
        hasMore: false,
        total: 1,
        status: 'idle',
        error: null,
      })
    })
  })
})

describe('useBrowseSession identity transition window', () => {
  // The reducer commits IDENTITY_CHANGED from a layout effect, one render after
  // the caller's identityKey prop changes. Consumers read identity-derived UI
  // and buffer-derived metadata in the same render body, so that render must
  // never be handed the previous identity's numbers.
  function collectFrames() {
    const frames: Array<{ requested: string; total: number | null; pending: boolean }> = []
    const storage = new MemoryStorage()
    const fetchPage = vi.fn(async (nextIdentity: Identity) => ({
      items: [{ id: nextIdentity.query === 'A' ? 1 : 2, label: nextIdentity.query }],
      cursor: null,
      hasMore: false,
      total: nextIdentity.query === 'A' ? 42 : 7,
    }))

    function Probe({ query }: { query: string }) {
      const session = useBrowseSession<Item, Cursor, Identity>({
        identity: identity(query),
        identityKey: key(query),
        adapter: { getItemId: (item) => item.id, fetchPage },
        scope,
        storage,
      })
      frames.push({
        requested: key(query),
        total: session.state.total,
        pending: session.state.pending,
      })
      return null
    }

    return { frames, Probe, storage, fetchPage }
  }

  it('never pairs a newly requested identity with the previous identity total in one render', async () => {
    const { frames, Probe } = collectFrames()

    const view = render(<Probe query="A" />)
    await waitFor(() => expect(frames.at(-1)?.total).toBe(42))

    frames.length = 0
    view.rerender(<Probe query="B" />)
    await waitFor(() => expect(frames.at(-1)?.total).toBe(7))

    // Every recorded frame here was rendered with identityKey B. 42 describes
    // A's list; surfacing it beside B is what let /e-hentai dereference a
    // metadata field belonging to a list it was no longer showing.
    expect(frames.every((frame) => frame.requested === key('B'))).toBe(true)
    expect(frames.map((frame) => frame.total)).not.toContain(42)
  })

  it('marks the pre-commit transition render as pending and clears it once the buffer commits', async () => {
    const { frames, Probe } = collectFrames()

    const view = render(<Probe query="A" />)
    await waitFor(() => expect(frames.at(-1)?.total).toBe(42))

    frames.length = 0
    view.rerender(<Probe query="B" />)
    await waitFor(() => expect(frames.at(-1)?.total).toBe(7))

    expect(frames[0]).toMatchObject({ total: null, pending: true })
    expect(frames.at(-1)).toMatchObject({ total: 7, pending: false })
  })
})
