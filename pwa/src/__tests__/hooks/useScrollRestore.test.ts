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
import { renderHook, act } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockGetItem, mockSetItem, mockRemoveItem, mockScrollTo } = vi.hoisted(() => ({
  mockGetItem: vi.fn(),
  mockSetItem: vi.fn(),
  mockRemoveItem: vi.fn(),
  mockScrollTo: vi.fn(),
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

import { useScrollRestore } from '@/hooks/useScrollRestore'

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
