import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const replace = vi.fn()
let searchStr = 'tab=search'

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
import { identityToUrlParams } from '@/lib/ehBrowseState'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

beforeEach(() => {
  searchStr = 'tab=search'
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('E-Hentai review blockers — ephemeral image sessions', () => {
  it('restores checkpointed image-search results when the same image_session remounts', () => {
    const first = renderHook(() => useEhBrowse())
    act(() =>
      first.result.current.actions.showExternalResults(
        [{ gid: 91, token: 'image-result' } as never],
        1,
      ),
    )
    const imageUrl = identityToUrlParams(first.result.current.state).toString()
    expect(imageUrl).toContain('image_session=')

    act(() => first.result.current.actions.checkpoint())
    first.unmount()

    searchStr = imageUrl
    const restored = renderHook(() => useEhBrowse())
    expect(restored.result.current.state.items.map((gallery) => gallery.gid)).toEqual([91])
    expect(restored.result.current.state.hasMore).toBe(false)
  })

  it('represents a missing image_session as explicitly expired, not Latest or a normal empty result', () => {
    searchStr = 'tab=search&image_session=missing-session'
    const { result } = renderHook(() => useEhBrowse())

    expect(result.current.state.ephemeralSession).toBe('missing-session')
    expect((result.current.state as { status: string }).status).toBe('expired')
  })
})

describe('E-Hentai review blockers — request-adjacent metadata generation', () => {
  it('does not let stale Favorites A mutate favCategories after A to B to A', async () => {
    searchStr = 'tab=favorites'
    const firstA = deferred<{
      galleries: never[]
      total: number
      has_next: boolean
      next_cursor: null
      categories: { index: number; name: string; count: number }[]
    }>()
    vi.mocked(api.eh.getFavorites).mockReturnValueOnce(firstA.promise as never)
    const { result } = renderHook(() => useEhBrowse())

    let request!: Promise<void>
    act(() => {
      request = result.current.loadMore()
    })
    act(() => result.current.actions.setTab('popular'))
    act(() => result.current.actions.setTab('favorites'))

    await act(async () => {
      firstA.resolve({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [{ index: 4, name: 'Stale category', count: 99 }],
      })
      await request
    })

    expect(result.current.favCategories).toEqual([])
  })
})
