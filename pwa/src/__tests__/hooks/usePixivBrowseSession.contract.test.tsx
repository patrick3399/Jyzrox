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
      [{ kind: 'user', preview: { user: { id: 23 }, illusts: [] } }],
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

// A browse snapshot is sessionStorage JSON with a 2 MB budget per source
// partition, so what a page stores per item decides how deep a list survives.
describe('usePixivBrowseSession stored item size', () => {
  const pximg = 'https://i.pximg.net/c/360x360_70/img-master/img/2024/05/17/12/30/45'
  const original = 'https://i.pximg.net/img-original/img/2024/05/17/12/30/45'

  function fatIllust(id: number, pages = 50) {
    return {
      id,
      title: `Manga chapter ${id}`,
      type: 'manga',
      image_urls: {
        square_medium: `${pximg}/${id}_p0_square1200.jpg`,
        medium: `${pximg}/${id}_p0_master1200.jpg`,
        large: `${pximg}/${id}_p0_master1200.jpg`,
        original: `${original}/${id}_p0.png`,
      },
      caption: `<strong>Chapter ${id}</strong><br />${'Long author note with <a href="https://example.com/x">links</a>. '.repeat(12)}`,
      user: {
        id: 13419413,
        name: 'Artist Name',
        account: 'artist_account',
        profile_image: 'https://i.pximg.net/user-profile/img/2020/01/01/00/00/00/12345_170.jpg',
      },
      tags: Array.from({ length: 12 }, (_, i) => ({
        name: `タグ${i}`,
        translated_name: `tag ${i}`,
      })),
      create_date: '2024-05-17T12:30:45+09:00',
      page_count: pages,
      width: 1200,
      height: 1700,
      sanity_level: 2,
      total_view: 123456,
      total_bookmarks: 7890,
      is_bookmarked: true,
      meta_pages: Array.from({ length: pages }, (_, p) => ({
        image_urls: {
          square_medium: `${pximg}/${id}_p${p}_square1200.jpg`,
          medium: `${pximg}/${id}_p${p}_master1200.jpg`,
          large: `${pximg}/${id}_p${p}_master1200.jpg`,
          original: `${original}/${id}_p${p}.png`,
        },
      })),
    }
  }

  async function fetchedItems(
    identity: PixivBrowseIdentity,
    method: 'search' | 'getFollowingFeed' | 'getMyBookmarks' | 'getFollowing' | 'ranking',
    response: unknown,
  ) {
    const usePixivBrowseSession = await loadHook()
    pixivApi[method].mockResolvedValueOnce(response)
    const { result } = renderHook(() => usePixivBrowseSession(ready(identity)))
    await waitFor(() => expect(result.current.state.items.length).toBeGreaterThan(0))
    return result.current.state.items
  }

  it('stores no caption, meta_pages or original/medium/large urls for a fetched illust', async () => {
    const items = await fetchedItems(
      { surface: 'bookmarks', restrict: 'public' },
      'getMyBookmarks',
      {
        illusts: [fatIllust(77)],
        next_offset: 1234,
      },
    )

    const illust = (items[0] as Extract<PixivBrowseItem, { kind: 'illust' }>).illust
    expect(illust).not.toHaveProperty('caption')
    expect(illust).not.toHaveProperty('meta_pages')
    expect(illust.image_urls).not.toHaveProperty('original')
    expect(illust.image_urls).not.toHaveProperty('medium')
    expect(illust.image_urls).not.toHaveProperty('large')
    expect(JSON.stringify(illust)).not.toContain('_p1_')
  })

  it('keeps exactly the fields the list cards and bookmark/download actions read', async () => {
    const items = await fetchedItems({ surface: 'feed' }, 'getFollowingFeed', {
      illusts: [fatIllust(78, 3)],
      next_offset: null,
    })

    const illust = (items[0] as Extract<PixivBrowseItem, { kind: 'illust' }>).illust
    expect(Object.keys(illust).sort()).toEqual([
      'id',
      'image_urls',
      'is_bookmarked',
      'page_count',
      'tags',
      'title',
      'total_bookmarks',
      'total_view',
      'user',
    ])
    expect(illust).toMatchObject({
      id: 78,
      title: 'Manga chapter 78',
      image_urls: { square_medium: `${pximg}/78_p0_square1200.jpg` },
      user: { id: 13419413, name: 'Artist Name' },
      page_count: 3,
      total_view: 123456,
      total_bookmarks: 7890,
      is_bookmarked: true,
    })
    expect(Object.keys(illust.image_urls as object)).toEqual(['square_medium'])
    expect(Object.keys(illust.user as object).sort()).toEqual(['id', 'name'])
    expect((illust.tags as unknown[])[0]).toEqual({ name: 'タグ0' })
    expect(illust.tags).toHaveLength(12)
  })

  it('turns the public search backend string tags into named tags the card can render', async () => {
    const usePixivBrowseSession = await loadHook()
    pixivApi.searchPublic.mockResolvedValueOnce({
      illusts: [
        { id: 79, title: 'Public', tags: ['blue', 'sky'], image_urls: { square_medium: 'u' } },
      ],
      next_offset: null,
    })
    const identity: PixivBrowseIdentity = {
      surface: 'search',
      query: 'miku',
      sort: 'date_desc',
      duration: '',
      backend: 'public',
    }

    const { result } = renderHook(() =>
      usePixivBrowseSession({ ...ready(identity), credentialsConfigured: false }),
    )
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    const illust = (result.current.state.items[0] as Extract<PixivBrowseItem, { kind: 'illust' }>)
      .illust
    expect(illust.tags).toEqual([{ name: 'blue' }, { name: 'sky' }])
  })

  // 30 illusts is one page; each is a 50-page manga, the worst realistic case
  // (a 50-page manga carries ~200 urls in meta_pages alone).
  // Per slim item: ~190 B of urls/ids + ~55 B title + ~20 B user + 12 tags at
  // ~20 B + counters ~60 B ≈ 600 B; the bound allows 1 KB per item so tag-heavy
  // works fit. At 30 KB a page, the 2 MB partition holds ~65 pages (~2000
  // illusts) instead of the ~3 pages the fat records (~690 KB a page) allowed.
  it('serializes a page of 30 fifty-page manga illusts to under 30 KB (fat records are ~690 KB)', async () => {
    const fat = Array.from({ length: 30 }, (_, i) => fatIllust(1000 + i))
    const fatBytes = JSON.stringify(fat).length
    expect(fatBytes).toBeGreaterThan(600_000)

    const items = await fetchedItems({ surface: 'feed' }, 'getFollowingFeed', {
      illusts: fat,
      next_offset: 31,
    })

    expect(items).toHaveLength(30)
    expect(JSON.stringify(items).length).toBeLessThan(30 * 1024)
  })

  it('stores only what a following card shows: the user and three preview thumbnails', async () => {
    const preview = {
      user: {
        id: 23,
        name: 'Followed',
        account: 'followed_account',
        profile_image: 'https://i.pximg.net/user-profile/23.jpg',
        is_followed: true,
        comment: 'x'.repeat(500),
      },
      illusts: [fatIllust(301), fatIllust(302), fatIllust(303), fatIllust(304)],
      novels: [{ id: 1 }],
      is_muted: false,
    }
    const items = await fetchedItems({ surface: 'following', restrict: 'public' }, 'getFollowing', {
      user_previews: [preview],
      next_offset: 30,
    })

    const stored = (items[0] as Extract<PixivBrowseItem, { kind: 'user' }>).preview
    expect(Object.keys(stored).sort()).toEqual(['illusts', 'user'])
    expect(stored.user).toEqual({
      id: 23,
      name: 'Followed',
      profile_image: 'https://i.pximg.net/user-profile/23.jpg',
      is_followed: true,
    })
    expect(stored.illusts).toEqual([
      { id: 301, image_urls: { square_medium: `${pximg}/301_p0_square1200.jpg` } },
      { id: 302, image_urls: { square_medium: `${pximg}/302_p0_square1200.jpg` } },
      { id: 303, image_urls: { square_medium: `${pximg}/303_p0_square1200.jpg` } },
    ])
  })

  it('gives a following preview without works an empty illusts list the card can read', async () => {
    const items = await fetchedItems({ surface: 'following', restrict: 'public' }, 'getFollowing', {
      user_previews: [{ user: { id: 24, name: 'Quiet' } }],
      next_offset: null,
    })

    expect((items[0] as Extract<PixivBrowseItem, { kind: 'user' }>).preview.illusts).toEqual([])
  })

  it('stores only the fields a ranking card reads', async () => {
    const items = await fetchedItems(
      { surface: 'ranking', mode: 'daily', content: 'all', r18: false },
      'ranking',
      {
        contents: [
          {
            illust_id: 55,
            title: 'Ranked',
            user_name: 'Ranker',
            url: `${pximg}/55_p0_master1200.jpg`,
            rank: 3,
            yes_rank: 4,
            tags: ['a', 'b', 'c'],
            profile_img: 'https://i.pximg.net/user-profile/x.jpg',
            illust_content_type: { sexual: 0, lo: false, grotesque: false },
            illust_series: false,
            view_count: 1,
            attr: '',
            width: 1,
            height: 2,
            date: '2024年05月17日 00:00',
          },
        ],
        has_next: false,
        rank_total: 500,
      },
    )

    expect(items).toEqual([
      {
        kind: 'ranking',
        entry: {
          illust_id: 55,
          title: 'Ranked',
          user_name: 'Ranker',
          url: `${pximg}/55_p0_master1200.jpg`,
          rank: 3,
        },
      },
    ])
  })

  it('still restores a snapshot written before items were slimmed, fat fields and all', async () => {
    const usePixivBrowseSession = await loadHook()
    const storage = new MemoryStorage()
    const scope: BrowseSnapshotScope = {
      userId: 'alice',
      tabId: 'tab-a',
      sourceId: 'pixiv',
      schemaVersion: 1,
    }
    const feed: PixivBrowseIdentity = { surface: 'feed' }
    const fat = fatIllust(91, 4)
    createBrowseSnapshotStore<PixivBrowseItem, Cursor>({ storage, scope }).save(
      pixivIdentityKey(feed),
      {
        pages: [[{ kind: 'illust', illust: fat }]],
        cursor: { kind: 'offset', value: 30 },
        hasMore: true,
        total: null,
        anchor: null,
        layout: null,
      },
    )

    const { result } = renderHook(() => usePixivBrowseSession(ready(feed, storage)))
    await waitFor(() => expect(result.current.state.items).toHaveLength(1))

    expect(result.current.state.items[0]).toMatchObject({
      kind: 'illust',
      illust: { id: 91, title: 'Manga chapter 91', page_count: 4 },
    })
    expect(pixivApi.getFollowingFeed).not.toHaveBeenCalled()
  })
})
