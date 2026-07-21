/**
 * useScrollRestore — Vitest test suite
 *
 * Covers:
 *   saveScroll  — stores window.scrollY into sessionStorage with the given key
 *   restore     — restores scroll position from sessionStorage when isReady becomes true
 *   restore     — removes the sessionStorage entry after restoring
 *   restore     — does NOT restore when isReady is false
 *   restore     — does NOT restore twice (restoredRef guard)
 *   isolation   — different keys are isolated from each other
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, useLayoutEffect } from 'react'
import { render, renderHook, act } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockGetItem, mockSetItem, mockRemoveItem, mockScrollTo, mockAddEventListener, mockRemoveEventListener } =
  vi.hoisted(() => ({
    mockGetItem: vi.fn(),
    mockSetItem: vi.fn(),
    mockRemoveItem: vi.fn(),
    mockScrollTo: vi.fn(),
    mockAddEventListener: vi.fn(),
    mockRemoveEventListener: vi.fn(),
  }))

// ── Module / global mocks ─────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()

  // sessionStorage
  Object.defineProperty(globalThis, 'sessionStorage', {
    value: {
      getItem: mockGetItem,
      setItem: mockSetItem,
      removeItem: mockRemoveItem,
    },
    writable: true,
    configurable: true,
  })

  // window.scrollTo
  Object.defineProperty(globalThis, 'window', {
    value: {
      ...globalThis.window,
      scrollTo: mockScrollTo,
      scrollY: 0,
      addEventListener: mockAddEventListener,
      removeEventListener: mockRemoveEventListener,
    },
    writable: true,
    configurable: true,
  })

  // requestAnimationFrame — call callback synchronously
  globalThis.requestAnimationFrame = (cb: FrameRequestCallback) => {
    cb(0)
    return 0
  }

  // Default: no saved scroll
  mockGetItem.mockReturnValue(null)
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Import hook after mocks ───────────────────────────────────────────

import { useScrollPositionRestore, useScrollRestore } from '@/hooks/useScrollRestore'

describe('useScrollPositionRestore', () => {
  it('restores once per logical view identity and rearms for a new identity', () => {
    const { rerender } = renderHook(
      ({ scrollY, restoreKey }: { scrollY: number; restoreKey: string }) =>
        useScrollPositionRestore({ scrollY, isReady: true, restoreKey }),
      { initialProps: { scrollY: 120, restoreKey: 'popular' } },
    )

    expect(mockScrollTo).toHaveBeenCalledWith(0, 120)
    rerender({ scrollY: 240, restoreKey: 'popular' })
    expect(mockScrollTo).toHaveBeenCalledTimes(1)

    rerender({ scrollY: 360, restoreKey: 'favorites' })
    expect(mockScrollTo).toHaveBeenCalledTimes(2)
    expect(mockScrollTo).toHaveBeenLastCalledWith(0, 360)
  })

  it('waits for content readiness before consuming the restore', () => {
    const onRestored = vi.fn()
    const { rerender } = renderHook(
      ({ ready }: { ready: boolean }) =>
        useScrollPositionRestore({
          scrollY: 480,
          isReady: ready,
          restoreKey: 'search',
          onRestored,
        }),
      { initialProps: { ready: false } },
    )

    expect(mockScrollTo).not.toHaveBeenCalled()
    expect(onRestored).not.toHaveBeenCalled()
    rerender({ ready: true })
    expect(mockScrollTo).toHaveBeenCalledWith(0, 480)
    expect(onRestored).toHaveBeenCalledTimes(1)
  })
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useScrollRestore — saveScroll()', () => {
  it('test_saveScroll_called_storesScrollYInSessionStorage', () => {
    Object.defineProperty(globalThis.window, 'scrollY', { value: 350, configurable: true })

    const { result } = renderHook(() => useScrollRestore('browse-page', false))

    act(() => {
      result.current.saveScroll()
    })

    expect(mockSetItem).toHaveBeenCalledWith('browse-page', '350')
  })

  it('test_saveScroll_differentKeys_storedWithCorrectKey', () => {
    Object.defineProperty(globalThis.window, 'scrollY', { value: 100, configurable: true })

    const { result } = renderHook(() => useScrollRestore('gallery-list', false))

    act(() => {
      result.current.saveScroll()
    })

    expect(mockSetItem).toHaveBeenCalledWith('gallery-list', '100')
  })
})

describe('useScrollRestore — restore on isReady', () => {
  it('test_restore_isReadyTrue_savedValue_callsScrollTo', () => {
    mockGetItem.mockReturnValue('480')

    renderHook(() => useScrollRestore('browse-page', true))

    expect(mockScrollTo).toHaveBeenCalledWith(0, 480)
  })

  it('test_restore_isReadyTrue_savedValue_removesSessionStorageEntry', () => {
    mockGetItem.mockReturnValue('480')

    renderHook(() => useScrollRestore('browse-page', true))

    expect(mockRemoveItem).toHaveBeenCalledWith('browse-page')
  })

  it('test_restore_isReadyFalse_doesNotRestoreScroll', () => {
    mockGetItem.mockReturnValue('480')

    renderHook(() => useScrollRestore('browse-page', false))

    expect(mockScrollTo).not.toHaveBeenCalled()
    expect(mockRemoveItem).not.toHaveBeenCalled()
  })

  it('test_restore_noSavedValue_doesNotCallScrollTo', () => {
    mockGetItem.mockReturnValue(null)

    renderHook(() => useScrollRestore('browse-page', true))

    expect(mockScrollTo).not.toHaveBeenCalled()
  })

  it('test_restore_isReadyBecomesTrue_onlyRestoresOnce', () => {
    mockGetItem.mockReturnValue('200')

    const { rerender } = renderHook(
      ({ ready }: { ready: boolean }) => useScrollRestore('browse-page', ready),
      { initialProps: { ready: true } },
    )

    // First render with isReady=true triggers restore
    expect(mockScrollTo).toHaveBeenCalledTimes(1)

    // Re-render with isReady=true again — restoredRef guard prevents second restore
    rerender({ ready: true })

    expect(mockScrollTo).toHaveBeenCalledTimes(1)
  })
})

describe('useScrollRestore — key isolation', () => {
  it('test_isolation_differentKeys_eachUsesOwnSessionStorageKey', () => {
    mockGetItem.mockImplementation((key: string) => {
      if (key === 'page-a') return '100'
      if (key === 'page-b') return '200'
      return null
    })

    renderHook(() => useScrollRestore('page-a', true))
    renderHook(() => useScrollRestore('page-b', true))

    expect(mockScrollTo).toHaveBeenCalledTimes(2)
    expect(mockRemoveItem).toHaveBeenCalledWith('page-a')
    expect(mockRemoveItem).toHaveBeenCalledWith('page-b')
  })
})

describe('useScrollRestore — saveScroll(pages)', () => {
  it('test_saveScroll_withPages_storesJsonFormat', () => {
    Object.defineProperty(globalThis.window, 'scrollY', { value: 350, configurable: true })
    const { result } = renderHook(() => useScrollRestore<{ id: number }>('feed-key', false))
    act(() => {
      result.current.saveScroll([{ id: 1 }, { id: 2 }])
    })
    expect(mockSetItem).toHaveBeenCalledWith(
      'feed-key',
      JSON.stringify({ scrollY: 350, pages: [{ id: 1 }, { id: 2 }] }),
    )
  })

  it('test_saveScroll_noArgs_storesLegacyStringFormat_backwardCompat', () => {
    Object.defineProperty(globalThis.window, 'scrollY', { value: 100, configurable: true })
    const { result } = renderHook(() => useScrollRestore('feed-key', false))
    act(() => {
      result.current.saveScroll()
    })
    expect(mockSetItem).toHaveBeenCalledWith('feed-key', '100')
  })
})

describe('useScrollRestore — persist mode', () => {
  it('test_persist_restore_doesNotRemoveSessionStorageEntry', () => {
    mockGetItem.mockReturnValue('480')

    renderHook(() => useScrollRestore('browse-page', true, { persist: true }))

    expect(mockScrollTo).toHaveBeenCalledWith(0, 480)
    expect(mockRemoveItem).not.toHaveBeenCalled()
  })

  it('test_persist_isReadyAndPersist_registersScrollListener', () => {
    renderHook(() => useScrollRestore('browse-page', true, { persist: true }))

    expect(mockAddEventListener).toHaveBeenCalledWith('scroll', expect.any(Function), {
      passive: true,
    })
  })

  it('test_persist_notReady_doesNotRegisterScrollListener', () => {
    // Inactive instances (e.g. a non-active pixiv sub-tab) must NOT capture, or
    // they would overwrite their own key with the active tab's scrollY.
    renderHook(() => useScrollRestore('browse-page', false, { persist: true }))

    expect(mockAddEventListener).not.toHaveBeenCalled()
  })

  it('test_persist_onScroll_writesScrollYPreservingPages', () => {
    mockGetItem.mockReturnValue(JSON.stringify({ scrollY: 0, pages: [{ id: 1 }] }))
    Object.defineProperty(globalThis.window, 'scrollY', { value: 640, configurable: true })

    renderHook(() => useScrollRestore<{ id: number }>('feed-key', true, { persist: true }))

    // Grab the registered scroll handler and invoke it
    const handler = mockAddEventListener.mock.calls.find((c) => c[0] === 'scroll')?.[1] as () => void
    expect(handler).toBeTypeOf('function')
    mockSetItem.mockClear()
    handler()

    expect(mockSetItem).toHaveBeenCalledWith(
      'feed-key',
      JSON.stringify({ scrollY: 640, pages: [{ id: 1 }] }),
    )
  })

  it('test_default_mode_doesNotRegisterScrollListener', () => {
    mockGetItem.mockReturnValue('480')

    renderHook(() => useScrollRestore('browse-page', true))

    expect(mockAddEventListener).not.toHaveBeenCalled()
    expect(mockRemoveItem).toHaveBeenCalledWith('browse-page')
  })

  it('removes the outgoing scroll listener before the incoming route layout phase', () => {
    const scrollListeners = new Set<() => void>()
    mockAddEventListener.mockImplementation((type: string, listener: () => void) => {
      if (type === 'scroll') scrollListeners.add(listener)
    })
    mockRemoveEventListener.mockImplementation((type: string, listener: () => void) => {
      if (type === 'scroll') scrollListeners.delete(listener)
    })
    mockGetItem.mockReturnValue(JSON.stringify({ scrollY: 640, pages: [{ id: 1 }] }))

    function SavedView() {
      useScrollRestore<{ id: number }>('feed-key', true, { persist: true })
      return null
    }

    function IncomingRoute() {
      useLayoutEffect(() => {
        // Next applies its scroll reset while mounting the incoming route. Any
        // outgoing passive listener still attached here would bank this 0.
        Object.defineProperty(globalThis.window, 'scrollY', { value: 0, configurable: true })
        scrollListeners.forEach((listener) => listener())
      }, [])
      return null
    }

    const view = render(createElement(SavedView))
    mockSetItem.mockClear()
    view.rerender(createElement(IncomingRoute))

    expect(scrollListeners.size).toBe(0)
    expect(mockSetItem).not.toHaveBeenCalledWith(
      'feed-key',
      JSON.stringify({ scrollY: 0, pages: [{ id: 1 }] }),
    )
  })
})

describe('useScrollRestore — restoredPages', () => {
  it('test_restoredPages_jsonFormat_returnsPages', () => {
    mockGetItem.mockReturnValue(JSON.stringify({ scrollY: 200, pages: [{ id: 42 }] }))
    const { result } = renderHook(() =>
      useScrollRestore<{ id: number }>('feed-key', true),
    )
    expect(result.current.restoredPages).toEqual([{ id: 42 }])
  })

  it('test_restoredPages_legacyStringFormat_returnsNull', () => {
    mockGetItem.mockReturnValue('480')
    const { result } = renderHook(() => useScrollRestore('feed-key', true))
    expect(result.current.restoredPages).toBeNull()
    // scroll still restores correctly (backward compat)
    expect(mockScrollTo).toHaveBeenCalledWith(0, 480)
  })

  it('test_restoredPages_noSavedValue_returnsNull', () => {
    mockGetItem.mockReturnValue(null)
    const { result } = renderHook(() => useScrollRestore('feed-key', true))
    expect(result.current.restoredPages).toBeNull()
  })

  it('test_restoredPages_emptyPagesArray_returnsNull_preventsSWRInitialSizeZero', () => {
    // Empty pages array must return null so initialSize stays at 1 (not 0)
    // initialSize:0 would cause SWR to skip all fetches indefinitely
    mockGetItem.mockReturnValue(JSON.stringify({ scrollY: 100, pages: [] }))
    const { result } = renderHook(() => useScrollRestore('feed-key', true))
    expect(result.current.restoredPages).toBeNull()
  })

  it('test_restoredPages_isReadyFalse_stillReadsPages_effectDoesNotRun', () => {
    // useState initializer reads pages even when isReady=false
    // but effect does NOT fire (so no scrollTo, no removeItem)
    mockGetItem.mockReturnValue(JSON.stringify({ scrollY: 100, pages: [{ id: 7 }] }))
    const { result } = renderHook(() =>
      useScrollRestore<{ id: number }>('feed-key', false),
    )
    expect(result.current.restoredPages).toEqual([{ id: 7 }])
    expect(mockScrollTo).not.toHaveBeenCalled()
    expect(mockRemoveItem).not.toHaveBeenCalled()
  })
})
