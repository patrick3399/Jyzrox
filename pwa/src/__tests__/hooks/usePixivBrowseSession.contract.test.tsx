import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createBrowseSnapshotStore, type BrowseSnapshotScope } from '@/lib/browse/snapshotStore'
import {
  pixivIdentityKey,
  type PixivBrowseIdentity,
  type PixivBrowseItem,
} from '@/lib/browse/pixiv'

const pixivApi = vi.hoisted(() => ({
  search: vi.fn(),
  searchPublic: vi.fn(),
  getFollowingFeed: vi.fn(),
  getMyBookmarks: vi.fn(),
  ranking: vi.fn(),
  getFollowing: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ api: { pixiv: pixivApi } }))
vi.mock('@/lib/ws', () => ({ useWsJobs: () => ({ lastJobUpdate: null }) }))

type Cursor = { kind: 'offset' | 'page'; value: number }
type HookOptions = {
  identity: PixivBrowseIdentity
  profileReady: boolean
  credentialsReady: boolean
  credentialsConfigured: boolean
  userId?: string
  tabId?: string
  storage?: Storage
}
type HookResult = {
  state: {
    items: PixivBrowseItem[]
    cursor: Cursor | null
    identityKey: string
  }
}
type PixivHook = (options: HookOptions) => HookResult

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
  const promise = new Promise<T>((onResolve) => {
    resolve = onResolve
  })
  return { promise, resolve }
}

async function loadHook(): Promise<PixivHook> {
  const hookModule = await vi.importActual<Record<string, unknown>>('@/hooks/usePixivBrowseSession')
  expect(hookModule.usePixivBrowseSession).toBeTypeOf('function')
  return hookModule.usePixivBrowseSession as PixivHook
}

const ready = (identity: PixivBrowseIdentity, storage = new MemoryStorage()): HookOptions => ({
  identity,
  profileReady: true,
  credentialsReady: true,
  credentialsConfigured: true,
  userId: 'alice',
  tabId: 'tab-a',
  storage,
})

beforeEach(() => {
  vi.clearAllMocks()
  pixivApi.search.mockResolvedValue({ illusts: [], next_offset: null })
  pixivApi.searchPublic.mockResolvedValue({ illusts: [], next_offset: null })
  pixivApi.getFollowingFeed.mockResolvedValue({ illusts: [], next_offset: null })
  pixivApi.getMyBookmarks.mockResolvedValue({ illusts: [], next_offset: null })
  pixivApi.ranking.mockResolvedValue({ contents: [], has_next: false, rank_total: 0 })
  pixivApi.getFollowing.mockResolvedValue({ user_previews: [], next_offset: null })
})

describe('usePixivBrowseSession cursor and item mapping', () => {
  it('maps authenticated Search to offset cursors and discriminated illust items', async () => {
    const usePixivBrowseSession = await loadHook()
    pixivApi.search.mockResolvedValueOnce({
      illusts: [{ id: 11 }],
      next_offset: 30,
      total: 80,
    })
    const identity: PixivBrowseIdentity = {
      surface: 'search',
      query: 'miku',
      sort: 'date_desc',
      duration: 'within_last_week',
      backend: 'authenticated',
    }

    const { result } = renderHook(() => usePixivBrowseSession(ready(identity)))
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    expect(pixivApi.search).toHaveBeenCalledWith(
      {
        word: 'miku',
        sort: 'date_desc',
        duration: 'within_last_week',
        offset: 0,
      },
      { signal: expect.any(AbortSignal) },
    )
    expect(result.current.state.items).toEqual([{ kind: 'illust', illust: { id: 11 } }])
    expect(result.current.state.cursor).toEqual({ kind: 'offset', value: 30 })
  })

  it('maps public Search order and offset-derived page cursors', async () => {
    const usePixivBrowseSession = await loadHook()
    pixivApi.searchPublic.mockResolvedValueOnce({ illusts: [{ id: 12 }], next_offset: 60 })
    const identity: PixivBrowseIdentity = {
      surface: 'search',
      query: 'miku',
      sort: 'popular_desc',
      duration: '',
      backend: 'public',
    }

    const { result } = renderHook(() =>
      usePixivBrowseSession({ ...ready(identity), credentialsConfigured: false }),
    )
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    expect(pixivApi.searchPublic).toHaveBeenCalledWith(
      { word: 'miku', order: 'popular_d', page: 1 },
      { signal: expect.any(AbortSignal) },
    )
    expect(result.current.state.cursor).toEqual({ kind: 'page', value: 2 })
  })

  it.each([
    [
      { surface: 'feed' } as PixivBrowseIdentity,
      'getFollowingFeed',
      { illusts: [{ id: 21 }], next_offset: 40 },
      [{ kind: 'illust', illust: { id: 21 } }],
    ],
    [
      { surface: 'bookmarks', restrict: 'private' } as PixivBrowseIdentity,
      'getMyBookmarks',
      { illusts: [{ id: 22 }], next_offset: 50 },
      [{ kind: 'illust', illust: { id: 22 } }],
    ],
    [
      { surface: 'following', restrict: 'public' } as PixivBrowseIdentity,
      'getFollowing',
      { user_previews: [{ user: { id: 23 } }], next_offset: 60 },
      [{ kind: 'user', preview: { user: { id: 23 } } }],
    ],
  ])(
    'maps %s to an offset cursor and its discriminated item kind',
    async (identity, method, response, items) => {
      const usePixivBrowseSession = await loadHook()
      pixivApi[method as 'getFollowingFeed'].mockResolvedValueOnce(response)

      const { result } = renderHook(() => usePixivBrowseSession(ready(identity)))
      await waitFor(() => expect(result.current.state.items).toHaveLength(1))

      expect(result.current.state.items).toEqual(items)
      expect(result.current.state.cursor).toEqual({
        kind: 'offset',
        value: response.next_offset,
      })
    },
  )

  it('maps Ranking to one-based page cursors and ranking items', async () => {
    const usePixivBrowseSession = await loadHook()
    pixivApi.ranking.mockResolvedValueOnce({
      contents: [{ illust_id: 31 }],
      has_next: true,
      rank_total: 70,
    })
    const identity: PixivBrowseIdentity = {
      surface: 'ranking',
      mode: 'weekly',
      content: 'manga',
      r18: false,
    }

    const { result } = renderHook(() => usePixivBrowseSession(ready(identity)))
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    expect(pixivApi.ranking).toHaveBeenCalledWith(
      { mode: 'weekly', content: 'manga', page: 1 },
      { signal: expect.any(AbortSignal) },
    )
    expect(result.current.state.items).toEqual([{ kind: 'ranking', entry: { illust_id: 31 } }])
    expect(result.current.state.cursor).toEqual({ kind: 'page', value: 2 })
  })
})

describe('usePixivBrowseSession isolation and readiness', () => {
  it('restores A and B snapshots independently by identity, user, and tab', async () => {
    const usePixivBrowseSession = await loadHook()
    const storage = new MemoryStorage()
    const scope: BrowseSnapshotScope = {
      userId: 'alice',
      tabId: 'tab-a',
      sourceId: 'pixiv',
      schemaVersion: 1,
    }
    const store = createBrowseSnapshotStore<PixivBrowseItem, Cursor>({ storage, scope })
    const a: PixivBrowseIdentity = { surface: 'feed' }
    const b: PixivBrowseIdentity = { surface: 'bookmarks', restrict: 'private' }
    const save = (identity: PixivBrowseIdentity, id: number, cursor: number) =>
      store.save(pixivIdentityKey(identity), {
        pages: [[{ kind: 'illust', illust: { id } }]],
        cursor: { kind: 'offset', value: cursor },
        hasMore: true,
        total: null,
        anchor: { itemId: `illust:${id}`, offset: 4, scrollY: 100 },
        layout: { columns: 4, width: 900, mode: 'grid' },
      })
    save(a, 41, 30)
    save(b, 42, 60)

    const view = renderHook(
      ({ identity }: { identity: PixivBrowseIdentity }) =>
        usePixivBrowseSession(ready(identity, storage)),
      {
        initialProps: { identity: a as PixivBrowseIdentity },
      },
    )
    await waitFor(() => expect(view.result.current.state.items).toHaveLength(1))
    expect(view.result.current.state.items[0]).toMatchObject({ illust: { id: 41 } })
    view.rerender({ identity: b })
    await waitFor(() =>
      expect(view.result.current.state.items[0]).toMatchObject({ illust: { id: 42 } }),
    )
    expect(pixivApi.getFollowingFeed).not.toHaveBeenCalled()
    expect(pixivApi.getMyBookmarks).not.toHaveBeenCalled()
  })

  it('aborts stale Search A across an A to B to A round trip', async () => {
    const usePixivBrowseSession = await loadHook()
    const requests: Array<{
      signal: AbortSignal
      request: ReturnType<typeof deferred<{ illusts: { id: number }[]; next_offset: null }>>
    }> = []
    pixivApi.search.mockImplementation((_params: unknown, init: RequestInit) => {
      const request = deferred<{ illusts: { id: number }[]; next_offset: null }>()
      requests.push({ signal: init.signal as AbortSignal, request })
      return request.promise
    })
    const search = (query: string): PixivBrowseIdentity => ({
      surface: 'search',
      query,
      sort: 'date_desc',
      duration: '',
      backend: 'authenticated',
    })
    const storage = new MemoryStorage()
    const view = renderHook(({ identity }) => usePixivBrowseSession(ready(identity, storage)), {
      initialProps: { identity: search('A') },
    })

    await waitFor(() => expect(requests).toHaveLength(1))
    view.rerender({ identity: search('B') })
    await waitFor(() => expect(requests).toHaveLength(2))
    view.rerender({ identity: search('A') })
    await waitFor(() => expect(requests).toHaveLength(3))
    expect(requests[0].signal.aborted).toBe(true)
    expect(requests[1].signal.aborted).toBe(true)

    await act(async () => {
      requests[0].request.resolve({ illusts: [{ id: 51 }], next_offset: null })
      requests[2].request.resolve({ illusts: [{ id: 53 }], next_offset: null })
      await Promise.resolve()
    })
    await waitFor(() =>
      expect(view.result.current.state.items[0]).toMatchObject({ illust: { id: 53 } }),
    )
  })

  it('waits for profile and credential resolution, permits public Search, and blocks private surfaces without credentials', async () => {
    const usePixivBrowseSession = await loadHook()
    const storage = new MemoryStorage()
    for (const key of [
      'pixiv_ranking_scrollY',
      'pixiv_feed_scrollY',
      'pixiv_bookmarks_scrollY',
      'pixiv_search_scrollY',
    ]) {
      storage.setItem(key, 'legacy')
    }
    const publicSearch: PixivBrowseIdentity = {
      surface: 'search',
      query: 'miku',
      sort: 'date_desc',
      duration: '',
      backend: 'public',
    }
    const view = renderHook((props: HookOptions) => usePixivBrowseSession(props), {
      initialProps: {
        ...ready(publicSearch, storage),
        profileReady: false,
        credentialsReady: false,
        credentialsConfigured: false,
        userId: undefined,
      } as HookOptions,
    })

    await Promise.resolve()
    expect(pixivApi.searchPublic).not.toHaveBeenCalled()
    expect(storage.getItem('pixiv_search_scrollY')).toBe('legacy')

    view.rerender({
      ...ready(publicSearch, storage),
      credentialsConfigured: false,
    })
    await waitFor(() => expect(pixivApi.searchPublic).toHaveBeenCalledOnce())
    for (const key of [
      'pixiv_ranking_scrollY',
      'pixiv_feed_scrollY',
      'pixiv_bookmarks_scrollY',
      'pixiv_search_scrollY',
    ]) {
      expect(storage.getItem(key)).toBeNull()
    }

    view.rerender({
      ...ready({ surface: 'feed' }, storage),
      credentialsConfigured: false,
    })
    await Promise.resolve()
    expect(pixivApi.getFollowingFeed).not.toHaveBeenCalled()
  })
})
