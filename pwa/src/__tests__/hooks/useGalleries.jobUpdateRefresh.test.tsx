/**
 * Task 0 regression: a cancelled / failed job rolls its gallery back (the row is
 * deleted or demoted), so the library grids must refresh on those statuses too.
 * Before the fix only `done` / `partial` refreshed and the stale "downloading"
 * card stayed until a manual reload.
 */
import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({
  job: null as { status: string } | null,
  globalMutate: vi.fn(),
}))

vi.mock('swr', () => ({
  default: vi.fn(() => ({})),
  useSWRConfig: () => ({ mutate: h.globalMutate }),
}))
vi.mock('swr/infinite', () => ({
  default: () => ({
    data: undefined,
    error: undefined,
    size: 1,
    setSize: vi.fn(),
    isValidating: false,
    isLoading: false,
    mutate: vi.fn(),
  }),
}))
vi.mock('@/lib/ws', () => ({ useWsJobs: () => ({ lastJobUpdate: h.job }) }))
vi.mock('@/lib/api', () => ({ api: {} }))

import { useInfiniteLibraryGalleries, useSearchGalleries } from '@/hooks/useGalleries'

/** The predicate the hook passes to the global mutate, applied to a key. */
function matchedKeys(predicateCall: unknown[] | undefined): string[] {
  const predicate = predicateCall?.[0] as ((key: unknown) => boolean) | undefined
  if (!predicate) return []
  return ['library/galleries/infinite', 'search/galleries'].filter((k) => predicate([k, {}]))
}

describe('library grids refresh on job updates', () => {
  beforeEach(() => {
    h.globalMutate.mockClear()
    h.job = null
  })

  it('refreshes library on cancelled job update', () => {
    h.job = { status: 'cancelled' }
    renderHook(() => useInfiniteLibraryGalleries({}))
    expect(h.globalMutate).toHaveBeenCalledTimes(1)
    expect(matchedKeys(h.globalMutate.mock.calls[0])).toEqual(['library/galleries/infinite'])
  })

  it('refreshes library on failed job update', () => {
    h.job = { status: 'failed' }
    renderHook(() => useInfiniteLibraryGalleries({}))
    expect(h.globalMutate).toHaveBeenCalledTimes(1)
  })

  it('refreshes library on done job update', () => {
    h.job = { status: 'done' }
    renderHook(() => useInfiniteLibraryGalleries({}))
    expect(h.globalMutate).toHaveBeenCalledTimes(1)
  })

  it('does not refresh library while the job is still running', () => {
    h.job = { status: 'running' }
    renderHook(() => useInfiniteLibraryGalleries({}))
    expect(h.globalMutate).not.toHaveBeenCalled()
  })

  it('refreshes search results on cancelled job update', () => {
    h.job = { status: 'cancelled' }
    renderHook(() => useSearchGalleries('cats'))
    expect(h.globalMutate).toHaveBeenCalledTimes(1)
    expect(matchedKeys(h.globalMutate.mock.calls[0])).toEqual(['search/galleries'])
  })
})
