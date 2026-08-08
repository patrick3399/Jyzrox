import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const push = vi.fn()
const replace = vi.fn()
let searchStr = ''

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))

vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(async () => ({ galleries: [], total: 0, next_gid: null })),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [],
      })),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0 })),
    },
  },
}))

import { useEhBrowse, type EhHistoryMode } from '@/hooks/useEhBrowse'
import { api } from '@/lib/api'
import {
  initialState,
  queryKey,
  reducer,
  serializeSnapshot,
  type EhBrowseState,
} from '@/lib/ehBrowseState'
import { snapshotStorageKey } from '@/lib/browse/snapshotStore'

function legacySearch(query: string, gid: number): string {
  let state = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
  state = reducer(state, { type: 'COMMIT_QUERY', query })
  state = reducer(state, {
    type: 'SEED',
    items: [{ gid, token: `token-${gid}` } as never],
    total: 1,
    cursor: null,
    hasMore: false,
  })
  return serializeSnapshot(state)
}

beforeEach(() => {
  searchStr = ''
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('E-Hentai legacy snapshot handoff', () => {
  it('consumes a legacy snapshot once and cannot re-import it into another scope', async () => {
    searchStr = 'q=legacy'
    sessionStorage.setItem('eh_browse_snapshot', legacySearch('legacy', 71))

    const first = renderHook(() => useEhBrowse({ userId: 'alice', tabId: 'tab-a' }))
    const aliceKey = snapshotStorageKey({
      userId: 'alice',
      tabId: 'tab-a',
      sourceId: 'ehentai',
      schemaVersion: 1,
    })
    await waitFor(() => expect(sessionStorage.getItem(aliceKey)).not.toBeNull())
    first.unmount()

    expect(sessionStorage.getItem('eh_browse_snapshot')).toBeNull()

    const second = renderHook(() => useEhBrowse({ userId: 'bob', tabId: 'tab-b' }))
    await act(async () => {})
    expect(second.result.current.state.items).toEqual([])
  })

  it('does not continuously mirror scoped checkpoints back into the legacy key', async () => {
    searchStr = 'q=legacy'
    sessionStorage.setItem('eh_browse_snapshot', legacySearch('legacy', 72))
    const view = renderHook(() => useEhBrowse({ userId: 'alice', tabId: 'tab-a' }))
    await act(async () => {})

    sessionStorage.removeItem('eh_browse_snapshot')
    act(() => view.result.current.actions.checkpoint())

    expect(sessionStorage.getItem('eh_browse_snapshot')).toBeNull()
  })
})

describe('E-Hentai unresolved user scope', () => {
  it('neither fetches nor persists browse state before the username is available', async () => {
    searchStr = 'q=pending-user'
    const view = renderHook(() => useEhBrowse({ userId: undefined, tabId: 'tab-a' }))

    await act(async () => view.result.current.loadMore())
    act(() => view.result.current.actions.checkpoint())

    expect(api.eh.search).not.toHaveBeenCalled()
    expect(
      Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)).filter(
        (key) => key?.startsWith('browse_session_v1:'),
      ),
    ).toEqual([])
  })
})

describe('E-Hentai identity history intent', () => {
  const cases = [
    ['query', (state: ReturnType<typeof useEhBrowse>, mode: EhHistoryMode) => state.actions.commitQuery('needle', mode)],
    ['filter', (state: ReturnType<typeof useEhBrowse>, mode: EhHistoryMode) => state.actions.setFilter({ minRating: 4 }, mode)],
    ['tab', (state: ReturnType<typeof useEhBrowse>, mode: EhHistoryMode) => state.actions.setTab('favorites', mode)],
  ] as const

  it.each(cases)('%s performs exactly one push with no competing replace', async (_name, commit) => {
    const pushState = vi.spyOn(window.history, 'pushState')
    const replaceState = vi.spyOn(window.history, 'replaceState')
    searchStr = 'tab=search'
    const view = renderHook(() => useEhBrowse({ userId: 'alice', tabId: 'tab-a' }))
    act(() => commit(view.result.current, 'push'))
    await act(async () => {})

    expect(pushState).toHaveBeenCalledTimes(1)
    expect(replaceState).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
    pushState.mockRestore()
    replaceState.mockRestore()
  })

  it.each(cases)('%s performs exactly one replace with no competing push', async (_name, commit) => {
    const pushState = vi.spyOn(window.history, 'pushState')
    const replaceState = vi.spyOn(window.history, 'replaceState')
    searchStr = 'tab=search'
    const view = renderHook(() => useEhBrowse({ userId: 'alice', tabId: 'tab-a' }))
    act(() => commit(view.result.current, 'replace'))
    await act(async () => {})

    expect(replaceState).toHaveBeenCalledTimes(1)
    expect(pushState).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
    pushState.mockRestore()
    replaceState.mockRestore()
  })
})

describe('E-Hentai cursor validation', () => {
  it.each([
    ['gid', 'q=cursor', { kind: 'gid', nextGid: -1 }],
    ['page', 'tab=toplist', { kind: 'page', page: 1.5 }],
  ])('rejects an out-of-range %s cursor instead of hydrating it', async (_name, url, cursor) => {
    searchStr = url
    const identity: EhBrowseState = {
      ...initialState,
      ...(url.startsWith('tab=toplist')
        ? { tab: 'toplist' as const }
        : { tab: 'search' as const, query: 'cursor' }),
    }
    const key = snapshotStorageKey({
      userId: 'alice',
      tabId: 'tab-a',
      sourceId: 'ehentai',
      schemaVersion: 1,
    })
    sessionStorage.setItem(
      key,
      JSON.stringify({
        version: 1,
        entries: [
          {
            identityKey: queryKey(identity),
            snapshot: {
              pages: [[{ gid: 99, token: 'invalid-cursor' }]],
              cursor,
              hasMore: true,
              total: 1,
              anchor: null,
              layout: null,
            },
            lastAccess: 1,
            metadata: { replayable: true, savedAt: 1, expiresAt: null },
          },
        ],
      }),
    )

    const view = renderHook(() => useEhBrowse({ userId: 'alice', tabId: 'tab-a' }))
    await act(async () => {})
    expect(view.result.current.state.items).toEqual([])
    expect(sessionStorage.getItem(key)).toBeNull()
  })
})
