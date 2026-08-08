import { Suspense, type ReactNode } from 'react'
import { act, render, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

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
      search: vi.fn(),
      getFavorites: vi.fn(),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0 })),
    },
  },
}))

import { useEhBrowse } from '@/hooks/useEhBrowse'
import { api } from '@/lib/api'
import { initialState, queryKey, reducer, serializeSnapshot } from '@/lib/ehBrowseState'
import { snapshotStorageKey } from '@/lib/browse/snapshotStore'

const scope = { userId: 'alice', tabId: 'tab-a' }
const storageScope = {
  ...scope,
  sourceId: 'ehentai',
  schemaVersion: 1,
}

function gallery(gid: number) {
  return { gid, token: `token-${gid}` } as never
}

function legacySearch(query: string, gid: number): string {
  let state = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
  state = reducer(state, { type: 'COMMIT_QUERY', query })
  state = reducer(state, {
    type: 'SEED',
    items: [gallery(gid)],
    total: 1,
    cursor: null,
    hasMore: false,
  })
  return serializeSnapshot(state)
}

function deferred<T>() {
  let resolvePromise!: (value: T) => void
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve
  })
  return { promise, resolve: resolvePromise }
}

beforeEach(() => {
  searchStr = ''
  sessionStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('E-Hentai live view ownership', () => {
  it('persists a memory-only anchor update made after an earlier checkpoint', async () => {
    searchStr = 'q=anchor'
    vi.mocked(api.eh.search).mockResolvedValue({
      galleries: [gallery(1)],
      total: 1,
      next_gid: null,
    } as never)
    const view = renderHook(() => useEhBrowse(scope))

    await act(async () => view.result.current.loadMore())
    act(() => {
      view.result.current.actions.checkpoint({ itemId: 1, offset: 10, scrollY: 100 })
    })
    act(() => {
      view.result.current.actions.setAnchor({ itemId: 1, offset: 20, scrollY: 900 })
    })
    act(() => view.result.current.actions.checkpoint())

    const raw = sessionStorage.getItem(snapshotStorageKey(storageScope))
    const partition = JSON.parse(raw ?? '{}') as {
      entries?: Array<{ identityKey: string; snapshot: { anchor: unknown } }>
    }
    const entry = partition.entries?.find((candidate) => candidate.identityKey === queryKey(view.result.current.state))
    expect(entry?.snapshot.anchor).toEqual({ itemId: 1, offset: 20, scrollY: 900 })
  })

  it('keeps ordered pages and request metadata across cleanup and remount', async () => {
    searchStr = 'tab=favorites'
    const categories = [{ index: 2, name: 'Favorites 2', count: 2 }]
    vi.mocked(api.eh.getFavorites)
      .mockResolvedValueOnce({
        galleries: [gallery(1)],
        total: 2,
        has_next: true,
        next_cursor: 'next-page',
        categories,
      } as never)
      .mockResolvedValueOnce({
        galleries: [gallery(2)],
        total: 2,
        has_next: false,
        next_cursor: null,
        categories,
      } as never)

    const first = renderHook(() => useEhBrowse(scope))
    await act(async () => first.result.current.loadMore())
    await act(async () => first.result.current.loadMore())
    first.unmount()

    const raw = sessionStorage.getItem(snapshotStorageKey(storageScope))
    const partition = JSON.parse(raw ?? '{}') as {
      entries?: Array<{
        snapshot: { pages: Array<Array<{ gid: number }>>; pageMeta?: unknown }
      }>
    }
    expect(partition.entries?.[0]?.snapshot.pages.map((page) => page.map((item) => item.gid))).toEqual([
      [1],
      [2],
    ])
    expect(partition.entries?.[0]?.snapshot.pageMeta).toEqual(categories)

    const restored = renderHook(() => useEhBrowse(scope))
    expect(restored.result.current.state.items.map((item) => item.gid)).toEqual([1, 2])
    expect(restored.result.current.favCategories).toEqual(categories)
    expect(api.eh.getFavorites).toHaveBeenCalledTimes(2)
  })
})

describe('E-Hentai legacy migration commit boundary', () => {
  it('does not consume legacy storage for a render that never commits', () => {
    searchStr = 'q=legacy'
    const legacy = legacySearch('legacy', 71)
    sessionStorage.setItem('eh_browse_snapshot', legacy)
    const suspended = new Promise<never>(() => {})

    function AbandonedBrowse(): ReactNode {
      useEhBrowse(scope)
      throw suspended
    }

    render(
      <Suspense fallback={<div>pending</div>}>
        <AbandonedBrowse />
      </Suspense>,
    )

    expect(sessionStorage.getItem('eh_browse_snapshot')).toBe(legacy)
    expect(sessionStorage.getItem(snapshotStorageKey(storageScope))).toBeNull()
  })

  it('migrates before coordinator hydration on a committed render', () => {
    searchStr = 'q=legacy'
    sessionStorage.setItem('eh_browse_snapshot', legacySearch('legacy', 72))

    const view = renderHook(() => useEhBrowse(scope))

    expect(view.result.current.state.items.map((item) => item.gid)).toEqual([72])
    expect(sessionStorage.getItem('eh_browse_snapshot')).toBeNull()
    expect(api.eh.search).not.toHaveBeenCalled()
  })

  it('treats storage exceptions as a missing legacy snapshot', () => {
    searchStr = 'q=legacy'
    const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
    const throwingStorage = {
      get length() {
        return 0
      },
      clear: vi.fn(),
      getItem: vi.fn(() => {
        throw new DOMException('blocked', 'SecurityError')
      }),
      key: vi.fn(() => null),
      removeItem: vi.fn(),
      setItem: vi.fn(),
    } satisfies Storage
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: throwingStorage,
      configurable: true,
    })

    try {
      expect(() => renderHook(() => useEhBrowse(scope))).not.toThrow()
    } finally {
      if (original) Object.defineProperty(globalThis, 'sessionStorage', original)
    }
  })

  it('falls back to memory when tab-id storage throws and no tabId was supplied', () => {
    const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
    const throwingStorage = {
      get length() {
        return 0
      },
      clear: vi.fn(),
      getItem: vi.fn(() => {
        throw new DOMException('blocked', 'SecurityError')
      }),
      key: vi.fn(() => null),
      removeItem: vi.fn(),
      setItem: vi.fn(() => {
        throw new DOMException('blocked', 'SecurityError')
      }),
    } satisfies Storage
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: throwingStorage,
      configurable: true,
    })

    try {
      expect(() => renderHook(() => useEhBrowse({ userId: 'alice' }))).not.toThrow()
    } finally {
      if (original) Object.defineProperty(globalThis, 'sessionStorage', original)
    }
  })
})

describe('E-Hentai canonical no-op and page intent', () => {
  it('does not checkpoint, route, or abort an in-flight request for advancedOpen', async () => {
    searchStr = 'q=needle'
    const append = deferred<{
      galleries: never[]
      total: number
      next_gid: null
    }>()
    vi.mocked(api.eh.search)
      .mockResolvedValueOnce({ galleries: [gallery(1)], total: 2, next_gid: 2 } as never)
      .mockReturnValueOnce(append.promise as never)
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const view = renderHook(() => useEhBrowse(scope))

    await act(async () => view.result.current.loadMore())
    let pending!: Promise<void>
    act(() => {
      pending = view.result.current.loadMore()
    })
    const signal = vi.mocked(api.eh.search).mock.calls[1]?.[1]?.signal
    setItem.mockClear()

    act(() => view.result.current.actions.setFilter({ advancedOpen: true }, 'push'))

    expect(signal?.aborted).toBe(false)
    expect(push).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
    expect(setItem).not.toHaveBeenCalled()

    append.resolve({ galleries: [], total: 2, next_gid: null })
    await act(async () => pending)
  })

  it('uses one atomic commitQuery path for uploader and watched-search intents', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/app/e-hentai/page.tsx'), 'utf8')
    const uploaderBody = source.match(/const searchUploader = useCallback\(([\s\S]*?)\n  \)/)?.[1]
    const watchedBody = source.match(/const openWatchedSearch = useCallback\(([\s\S]*?)\n  \)/)?.[1]

    expect(uploaderBody).toContain('commitSearch(value)')
    expect(uploaderBody).not.toContain("actions.setTab('search')")
    expect(watchedBody).toContain('commitSearch(value)')
    expect(watchedBody).not.toContain("actions.setTab('search')")
  })
})
