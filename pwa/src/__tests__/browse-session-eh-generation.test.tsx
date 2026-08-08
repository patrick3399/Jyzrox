import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const replace = vi.fn()
let searchStr = 'q=A'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))

vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(),
      getFavorites: vi.fn(),
      getPopular: vi.fn(),
      getToplist: vi.fn(),
    },
  },
}))

import { useEhBrowse } from '@/hooks/useEhBrowse'
import { api } from '@/lib/api'
import { queryKey } from '@/lib/ehBrowseState'

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (error: Error) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  searchStr = 'q=A'
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('E-Hentai browse-session request generation', () => {
  it('rejects a late success after A to B to A returns to the same identity key', async () => {
    const firstA = deferred<{
      galleries: { gid: number; token: string }[]
      total: number
      next_gid: number | null
    }>()
    vi.mocked(api.eh.search).mockReturnValueOnce(firstA.promise as never)
    const { result } = renderHook(() => useEhBrowse())

    let request!: Promise<void>
    act(() => {
      request = result.current.loadMore()
    })
    act(() => result.current.actions.commitQuery('B'))
    act(() => result.current.actions.commitQuery('A'))

    await act(async () => {
      firstA.resolve({ galleries: [{ gid: 99, token: 'late' }], total: 1, next_gid: null })
      await request
    })

    expect(result.current.state.query).toBe('A')
    expect(result.current.state.items).toEqual([])
    expect(result.current.state.status).toBe('idle')
  })

  it('rejects a late error after A to B to A returns to the same identity key', async () => {
    const firstA = deferred<never>()
    vi.mocked(api.eh.search).mockReturnValueOnce(firstA.promise)
    const { result } = renderHook(() => useEhBrowse())

    let request!: Promise<void>
    act(() => {
      request = result.current.loadMore()
    })
    act(() => result.current.actions.commitQuery('B'))
    act(() => result.current.actions.commitQuery('A'))

    await act(async () => {
      firstA.reject(new Error('late A failure'))
      await request
    })

    expect(result.current.state.query).toBe('A')
    expect(result.current.state.error).toBeNull()
    expect(result.current.state.status).toBe('idle')
  })
})

describe('E-Hentai image-search session identity', () => {
  it('does not reuse Latest or another image-search session identity', () => {
    const { result } = renderHook(() => useEhBrowse())

    act(() => result.current.actions.commitQuery(''))
    const latestKey = queryKey(result.current.state)

    act(() =>
      result.current.actions.showExternalResults(
        [{ gid: 1, token: 'first-image-search' } as never],
        1,
      ),
    )
    const firstImageSearchKey = queryKey(result.current.state)

    act(() =>
      result.current.actions.showExternalResults(
        [{ gid: 2, token: 'second-image-search' } as never],
        1,
      ),
    )
    const secondImageSearchKey = queryKey(result.current.state)

    expect(firstImageSearchKey).not.toBe(latestKey)
    expect(secondImageSearchKey).not.toBe(latestKey)
    expect(secondImageSearchKey).not.toBe(firstImageSearchKey)
  })
})

describe('E-Hentai empty browse-session checkpoint', () => {
  it('does not resurrect an older nonempty snapshot after the same identity becomes empty', () => {
    const { result } = renderHook(() => useEhBrowse())

    act(() =>
      result.current.dispatch({
        type: 'SEED',
        items: [{ gid: 7, token: 'old-result' } as never],
        total: 1,
        cursor: null,
        hasMore: false,
      }),
    )
    act(() => result.current.actions.commitQuery('B'))
    act(() => result.current.actions.commitQuery('A'))
    expect(result.current.state.items).toHaveLength(1)

    act(() =>
      result.current.dispatch({
        type: 'SEED',
        items: [],
        total: 0,
        cursor: null,
        hasMore: false,
      }),
    )
    act(() => result.current.actions.commitQuery('C'))
    act(() => result.current.actions.commitQuery('A'))

    expect(result.current.state.items).toEqual([])
    expect(result.current.state.total).toBe(0)
    expect(result.current.state.hasMore).toBe(false)
  })

  it('does not resurrect an older nonempty snapshot after the same identity enters an empty error state', () => {
    const { result } = renderHook(() => useEhBrowse())

    act(() =>
      result.current.dispatch({
        type: 'SEED',
        items: [{ gid: 8, token: 'old-result' } as never],
        total: 1,
        cursor: null,
        hasMore: false,
      }),
    )
    act(() => result.current.actions.commitQuery('B'))
    act(() => result.current.actions.commitQuery('A'))

    act(() =>
      result.current.dispatch({
        type: 'RESTORE',
        snapshot: {
          items: [],
          total: null,
          cursor: null,
          hasMore: true,
          status: 'error',
          error: 'current failure',
        },
      }),
    )
    act(() => result.current.actions.commitQuery('C'))
    act(() => result.current.actions.commitQuery('A'))

    expect(result.current.state.items).toEqual([])
  })
})
