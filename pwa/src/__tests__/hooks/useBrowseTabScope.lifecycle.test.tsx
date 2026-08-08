import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const claimBrowseTabScope = vi.hoisted(() => vi.fn())

vi.mock('@/lib/browse/tabScope', () => ({
  claimBrowseTabScope,
  commitBrowseTabId: (storage: Storage, tabId: string) => {
    storage.setItem('browse_session_tab_id_v1', tabId)
  },
}))

import { useBrowseTabScope } from '@/hooks/useBrowseTabScope'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => {
    resolve = yes
  })
  return { promise, resolve }
}

beforeEach(() => {
  claimBrowseTabScope.mockReset()
  window.sessionStorage.clear()
})

describe('useBrowseTabScope document lifecycle', () => {
  it('stays unready until claimed, releases on pagehide, and reacquires on pageshow', async () => {
    const first = deferred<{ tabId: string; release: () => void }>()
    const second = deferred<{ tabId: string; release: () => void }>()
    const releaseFirst = vi.fn()
    const releaseSecond = vi.fn()
    claimBrowseTabScope
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const view = renderHook(() =>
      useBrowseTabScope({ storage: window.sessionStorage, enabled: true }),
    )
    expect(view.result.current).toEqual({ tabId: 'pending', ready: false })

    await act(async () => {
      first.resolve({ tabId: 'tab-before-bfcache', release: releaseFirst })
      await first.promise
    })
    await waitFor(() =>
      expect(view.result.current).toEqual({ tabId: 'tab-before-bfcache', ready: true }),
    )

    act(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })))
    expect(releaseFirst).toHaveBeenCalledOnce()
    expect(view.result.current).toEqual({ tabId: 'pending', ready: false })

    act(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })))
    expect(claimBrowseTabScope).toHaveBeenCalledTimes(2)
    expect(view.result.current).toEqual({ tabId: 'pending', ready: false })

    await act(async () => {
      second.resolve({ tabId: 'tab-after-bfcache', release: releaseSecond })
      await second.promise
    })
    await waitFor(() =>
      expect(view.result.current).toEqual({ tabId: 'tab-after-bfcache', ready: true }),
    )

    view.unmount()
    expect(releaseSecond).toHaveBeenCalledOnce()
  })

  it('does not let a stale pre-pagehide claim persist over the active pageshow claim', async () => {
    const staleGate = deferred<void>()
    const releaseStale = vi.fn()
    const releaseActive = vi.fn()
    const storageKey = 'browse_session_tab_id_v1'
    claimBrowseTabScope
      .mockImplementationOnce(async ({ storage }: { storage: Storage }) => {
        await staleGate.promise
        storage.setItem(storageKey, 'stale-before-pagehide')
        return { tabId: 'stale-before-pagehide', release: releaseStale }
      })
      .mockImplementationOnce(async ({ storage }: { storage: Storage }) => {
        storage.setItem(storageKey, 'active-after-pageshow')
        return { tabId: 'active-after-pageshow', release: releaseActive }
      })

    const view = renderHook(() =>
      useBrowseTabScope({ storage: window.sessionStorage, enabled: true }),
    )
    expect(view.result.current.ready).toBe(false)

    act(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })))
    act(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })))
    await waitFor(() =>
      expect(view.result.current).toEqual({ tabId: 'active-after-pageshow', ready: true }),
    )
    expect(window.sessionStorage.getItem(storageKey)).toBe('active-after-pageshow')

    await act(async () => {
      staleGate.resolve()
      await staleGate.promise
    })
    await waitFor(() => expect(releaseStale).toHaveBeenCalledOnce())

    expect(view.result.current).toEqual({ tabId: 'active-after-pageshow', ready: true })
    expect(window.sessionStorage.getItem(storageKey)).toBe('active-after-pageshow')
    view.unmount()
    expect(releaseActive).toHaveBeenCalledOnce()
  })
})
