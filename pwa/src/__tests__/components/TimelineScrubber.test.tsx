/**
 * TimelineScrubber — Vitest component test suite
 *
 * Covers:
 *   Does not render when enabled=false
 *   Does not render when minAt === maxAt (no range)
 *   Renders track and thumb when valid range + enabled
 *   REGRESSION: drag does not re-attach global listeners on every mousemove
 *     (bug: handleDragEnd depended on thumbRatio state, so every drag move recreated the
 *      callback, causing the useEffect to teardown and re-attach all 4 global event
 *      listeners on every single mousemove — fix uses thumbRatioRef instead)
 *   Fires onJump on mouseup after drag
 *   Cleans up listeners on unmount during drag
 *
 * Mock strategy:
 *   - @/lib/i18n → stub t() to return the key
 *   - window.addEventListener spy to count listener registrations
 *   - getBoundingClientRect stubbed on the track element for stable drag calculations
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, fireEvent, act } from '@testing-library/react'

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

// ── Import component after mocks ──────────────────────────────────────

import { TimelineScrubber } from '@/components/TimelineScrubber'

// ── Helpers ───────────────────────────────────────────────────────────

const MIN_AT = new Date('2020-01-01T00:00:00Z')
const MAX_AT = new Date('2024-12-31T00:00:00Z')

function defaultProps(overrides: Partial<React.ComponentProps<typeof TimelineScrubber>> = {}) {
  return {
    minAt: MIN_AT,
    maxAt: MAX_AT,
    enabled: true,
    onJump: vi.fn(),
    ...overrides,
  }
}

// Stub getBoundingClientRect on the track element so getRatioFromY works deterministically.
// The track is 400px tall, positioned at top=0. clientY=200 → ratio=0.5.
function stubTrackRect(trackEl: Element) {
  vi.spyOn(trackEl, 'getBoundingClientRect').mockReturnValue({
    top: 0,
    bottom: 400,
    left: 0,
    right: 10,
    height: 400,
    width: 10,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
}

// ── Setup / Teardown ──────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  // jsdom defaults: scrollHeight = innerHeight = 768, so maxScroll = 0.
  // Stub scrollHeight > innerHeight so scrollTo / scroll logic runs.
  Object.defineProperty(document.documentElement, 'scrollHeight', {
    configurable: true,
    get: () => 2000,
  })
  Object.defineProperty(window, 'innerHeight', {
    configurable: true,
    get: () => 768,
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('TimelineScrubber — rendering', () => {
  it('test_timelineScrubber_enabledFalse_doesNotRender', () => {
    const { container } = render(<TimelineScrubber {...defaultProps({ enabled: false })} />)
    expect(container.innerHTML).toBe('')
  })

  it('test_timelineScrubber_minAtEqualsMaxAt_doesNotRender', () => {
    const sameDate = new Date('2023-01-01T00:00:00Z')
    const { container } = render(
      <TimelineScrubber {...defaultProps({ minAt: sameDate, maxAt: sameDate })} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('test_timelineScrubber_nullMinAt_doesNotRender', () => {
    const { container } = render(<TimelineScrubber {...defaultProps({ minAt: null })} />)
    expect(container.innerHTML).toBe('')
  })

  it('test_timelineScrubber_validRangeAndEnabled_rendersTrack', () => {
    const { container } = render(<TimelineScrubber {...defaultProps()} />)
    expect(container.querySelector('.timeline-scrubber__track')).toBeTruthy()
  })

  it('test_timelineScrubber_validRangeAndEnabled_rendersThumb', () => {
    const { container } = render(<TimelineScrubber {...defaultProps()} />)
    expect(container.querySelector('.timeline-scrubber__thumb')).toBeTruthy()
  })
})

describe('TimelineScrubber — drag listener stability (regression bug #3)', () => {
  it('test_timelineScrubber_drag_attachesMousemoveListenerExactlyOnceOnDragStart_regressionListenerReattachOnEveryMove', () => {
    // REGRESSION: When handleDragEnd captured thumbRatio state instead of thumbRatioRef,
    // every drag move caused a state update → handleDragEnd was recreated → the useEffect
    // dependency array changed → useEffect tore down and re-attached all 4 global event
    // listeners. This meant N mousemove events = N+1 sets of attached listeners (leak).
    // Fix: handleDragEnd now reads thumbRatioRef.current, keeping itself stable during drag.
    //
    // This test verifies the fix: mousemove listener is attached exactly once when drag
    // begins and is NOT re-attached during subsequent mousemove events.

    const addEventListenerSpy = vi.spyOn(window, 'addEventListener')

    const { container } = render(<TimelineScrubber {...defaultProps()} />)
    const track = container.querySelector('.timeline-scrubber__track') as HTMLElement
    stubTrackRect(track)

    // Count baseline calls before drag (scroll listener etc.)
    const baselineCount = addEventListenerSpy.mock.calls.filter(
      ([eventName]) => eventName === 'mousemove',
    ).length

    // Start drag
    act(() => {
      fireEvent.mouseDown(track, { clientY: 100, button: 0 })
    })

    const afterMouseDownCount = addEventListenerSpy.mock.calls.filter(
      ([eventName]) => eventName === 'mousemove',
    ).length
    // Exactly one mousemove listener should have been attached when drag started
    expect(afterMouseDownCount - baselineCount).toBe(1)

    // Move the mouse several times — these should NOT trigger re-attachment
    act(() => {
      fireEvent.mouseMove(window, { clientY: 150 })
      fireEvent.mouseMove(window, { clientY: 200 })
      fireEvent.mouseMove(window, { clientY: 250 })
    })

    const afterMovesCount = addEventListenerSpy.mock.calls.filter(
      ([eventName]) => eventName === 'mousemove',
    ).length
    // Still exactly one — no re-attachment during drag moves
    expect(afterMovesCount - baselineCount).toBe(1)

    // End drag for cleanup
    act(() => {
      fireEvent.mouseUp(window)
    })
  })

  it('test_timelineScrubber_drag_attachesAllFourListenersOnce_regressionListenerReattachOnEveryMove', () => {
    // Verifies all 4 listeners (mousemove, mouseup, touchmove, touchend) are each
    // attached exactly once across multiple mousemove events during drag.
    const addEventListenerSpy = vi.spyOn(window, 'addEventListener')

    const { container } = render(<TimelineScrubber {...defaultProps()} />)
    const track = container.querySelector('.timeline-scrubber__track') as HTMLElement
    stubTrackRect(track)

    const countBefore = (eventName: string) =>
      addEventListenerSpy.mock.calls.filter(([e]) => e === eventName).length

    const beforeDrag = {
      mousemove: countBefore('mousemove'),
      mouseup: countBefore('mouseup'),
      touchmove: countBefore('touchmove'),
      touchend: countBefore('touchend'),
    }

    act(() => {
      fireEvent.mouseDown(track, { clientY: 100, button: 0 })
    })

    // Simulate several moves
    act(() => {
      fireEvent.mouseMove(window, { clientY: 120 })
      fireEvent.mouseMove(window, { clientY: 140 })
      fireEvent.mouseMove(window, { clientY: 160 })
    })

    expect(countBefore('mousemove') - beforeDrag.mousemove).toBe(1)
    expect(countBefore('mouseup') - beforeDrag.mouseup).toBe(1)
    expect(countBefore('touchmove') - beforeDrag.touchmove).toBe(1)
    expect(countBefore('touchend') - beforeDrag.touchend).toBe(1)

    act(() => {
      fireEvent.mouseUp(window)
    })
  })
})

describe('TimelineScrubber — onJump callback', () => {
  it('test_timelineScrubber_mouseup_firesOnJumpWithISOString', () => {
    const onJump = vi.fn()
    const { container } = render(<TimelineScrubber {...defaultProps({ onJump })} />)
    const track = container.querySelector('.timeline-scrubber__track') as HTMLElement
    stubTrackRect(track)

    act(() => {
      fireEvent.mouseDown(track, { clientY: 0, button: 0 })
    })
    act(() => {
      fireEvent.mouseUp(window)
    })

    expect(onJump).toHaveBeenCalledOnce()
    // onJump should receive a valid ISO 8601 string
    const arg = onJump.mock.calls[0][0] as string
    expect(() => new Date(arg)).not.toThrow()
    expect(typeof arg).toBe('string')
    expect(arg).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })
})

describe('TimelineScrubber — cleanup', () => {
  it('test_timelineScrubber_unmountDuringDrag_removesAllFourGlobalListeners', () => {
    const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

    const { container, unmount } = render(<TimelineScrubber {...defaultProps()} />)
    const track = container.querySelector('.timeline-scrubber__track') as HTMLElement
    stubTrackRect(track)

    act(() => {
      fireEvent.mouseDown(track, { clientY: 100, button: 0 })
    })

    removeEventListenerSpy.mockClear()

    act(() => {
      unmount()
    })

    const removedEvents = removeEventListenerSpy.mock.calls.map(([eventName]) => eventName)
    expect(removedEvents).toContain('mousemove')
    expect(removedEvents).toContain('mouseup')
    expect(removedEvents).toContain('touchmove')
    expect(removedEvents).toContain('touchend')
  })
})
