/**
 * useLongPress hook — Vitest test suite
 *
 * Covers:
 *   Long-press fires onLongPress after threshold
 *   Short tap does not fire onLongPress
 *   Movement beyond moveThreshold cancels the long-press
 *   touchend calls preventDefault after a successful long-press (no phantom click)
 *   touchend calls preventDefault even after contextmenu fires on touch devices
 *     (regression: firedRef must not be reset in onContextMenu before touchend runs)
 *   Desktop right-click (contextmenu without touchstart) fires onLongPress
 *   Desktop right-click does not fire onLongPress twice if contextmenu fires after touch timer
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { useLongPress } from '@/hooks/useLongPress'

// ── Helpers ───────────────────────────────────────────────────────────

/**
 * Build a minimal synthetic React.TouchEvent-like object.
 * renderHook returns handler refs; we call them directly rather than
 * dispatching DOM events so we can inspect e.preventDefault() calls.
 */
function makeTouchEvent(clientX = 0, clientY = 0): React.TouchEvent {
  return {
    touches: [{ clientX, clientY }] as unknown as React.TouchList,
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
  } as unknown as React.TouchEvent
}

function makeMouseEvent(): React.MouseEvent {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
  } as unknown as React.MouseEvent
}

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useLongPress — basic long-press firing', () => {
  it('fires onLongPress after threshold elapses', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress, threshold: 500 }))

    const touchStart = makeTouchEvent(0, 0)
    act(() => {
      result.current.onTouchStart(touchStart)
      vi.advanceTimersByTime(500)
    })

    expect(onLongPress).toHaveBeenCalledOnce()
  })

  it('does not fire onLongPress if touchend occurs before threshold', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress, threshold: 500 }))

    const touchStart = makeTouchEvent(0, 0)
    const touchEnd = makeTouchEvent(0, 0)
    act(() => {
      result.current.onTouchStart(touchStart)
      vi.advanceTimersByTime(300)
      result.current.onTouchEnd(touchEnd)
      vi.advanceTimersByTime(300) // remaining time — should NOT fire
    })

    expect(onLongPress).not.toHaveBeenCalled()
  })
})

describe('useLongPress — move cancellation', () => {
  it('cancels long-press when finger moves beyond moveThreshold', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() =>
      useLongPress({ onLongPress, threshold: 500, moveThreshold: 10 }),
    )

    const touchStart = makeTouchEvent(0, 0)
    const touchMove = makeTouchEvent(20, 0) // dx=20 > moveThreshold=10
    act(() => {
      result.current.onTouchStart(touchStart)
      result.current.onTouchMove(touchMove)
      vi.advanceTimersByTime(500)
    })

    expect(onLongPress).not.toHaveBeenCalled()
  })
})

describe('useLongPress — touchend preventDefault after successful long-press', () => {
  it('calls preventDefault on touchend after a successful long-press', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress, threshold: 500 }))

    const touchStart = makeTouchEvent(0, 0)
    const touchEnd = makeTouchEvent(0, 0)
    act(() => {
      result.current.onTouchStart(touchStart)
      vi.advanceTimersByTime(500)
      result.current.onTouchEnd(touchEnd)
    })

    expect(touchEnd.preventDefault).toHaveBeenCalled()
  })

  it('does NOT call preventDefault on touchend when long-press did not fire', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress, threshold: 500 }))

    const touchStart = makeTouchEvent(0, 0)
    const touchEnd = makeTouchEvent(0, 0)
    act(() => {
      result.current.onTouchStart(touchStart)
      vi.advanceTimersByTime(200) // timer not yet elapsed
      result.current.onTouchEnd(touchEnd)
    })

    expect(touchEnd.preventDefault).not.toHaveBeenCalled()
  })
})

describe('useLongPress — phantom click regression (touch + contextmenu sequence)', () => {
  /**
   * Regression test for the phantom click bug on touch devices:
   *
   * Event sequence on mobile after a long-press:
   *   1. touchstart  → firedRef = false, 500 ms timer starts
   *   2. timer fires → firedRef = true, onLongPress() called, context menu opens
   *   3. browser fires contextmenu event → onContextMenu runs
   *   4. touchend    → must call preventDefault to block synthetic click
   *
   * Before the fix, onContextMenu reset firedRef = false at step 3, so step 4
   * saw firedRef = false and skipped preventDefault → browser generated a
   * synthetic click that hit the context menu item at the touch position
   * (e.g. "Favorite"), triggering an unintended action.
   */
  it('touchend calls preventDefault even after contextmenu fires on touch devices', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress, threshold: 500 }))

    const touchStart = makeTouchEvent(0, 0)
    const contextMenuEvent = makeMouseEvent()
    const touchEnd = makeTouchEvent(0, 0)

    act(() => {
      // Step 1: touchstart
      result.current.onTouchStart(touchStart)
      // Step 2: timer fires → firedRef becomes true, onLongPress called
      vi.advanceTimersByTime(500)
      // Step 3: browser fires contextmenu (must NOT reset firedRef)
      result.current.onContextMenu(contextMenuEvent)
      // Step 4: touchend — must still call preventDefault
      result.current.onTouchEnd(touchEnd)
    })

    // onLongPress was already called by the timer; contextmenu should NOT call it again
    expect(onLongPress).toHaveBeenCalledOnce()
    // The critical assertion: preventDefault must be called to block the phantom click
    expect(touchEnd.preventDefault).toHaveBeenCalled()
  })

  it('firedRef is reset after touchend so a subsequent gesture works normally', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress, threshold: 500 }))

    // First gesture: full long-press + contextmenu + touchend
    act(() => {
      result.current.onTouchStart(makeTouchEvent(0, 0))
      vi.advanceTimersByTime(500)
      result.current.onContextMenu(makeMouseEvent())
      result.current.onTouchEnd(makeTouchEvent(0, 0))
    })

    // Second gesture: short tap (should not fire onLongPress)
    const secondTouchEnd = makeTouchEvent(0, 0)
    act(() => {
      result.current.onTouchStart(makeTouchEvent(0, 0))
      vi.advanceTimersByTime(200) // not enough time
      result.current.onTouchEnd(secondTouchEnd)
    })

    // onLongPress fired once (first gesture only)
    expect(onLongPress).toHaveBeenCalledOnce()
    // Second touchend should NOT call preventDefault (no long-press fired)
    expect(secondTouchEnd.preventDefault).not.toHaveBeenCalled()
  })
})

describe('useLongPress — desktop right-click (contextmenu without touch)', () => {
  it('fires onLongPress on desktop right-click via contextmenu event', () => {
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress }))

    const contextMenuEvent = makeMouseEvent()
    act(() => {
      result.current.onContextMenu(contextMenuEvent)
    })

    expect(onLongPress).toHaveBeenCalledOnce()
    expect(contextMenuEvent.preventDefault).toHaveBeenCalled()
  })

  it('does not fire onLongPress twice when contextmenu fires after touch timer on desktop', () => {
    // Simulate a scenario where both touchstart timer AND contextmenu fire.
    // onLongPress should be called exactly once (timer fired it; contextmenu
    // sees firedRef=true and skips calling onLongPress again).
    const onLongPress = vi.fn()
    const { result } = renderHook(() => useLongPress({ onLongPress, threshold: 500 }))

    act(() => {
      result.current.onTouchStart(makeTouchEvent(0, 0))
      vi.advanceTimersByTime(500) // timer fires → firedRef=true, onLongPress called
      result.current.onContextMenu(makeMouseEvent()) // should NOT call onLongPress again
      result.current.onTouchEnd(makeTouchEvent(0, 0))
    })

    expect(onLongPress).toHaveBeenCalledOnce()
  })
})
