import { act, fireEvent, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePinchZoom } from '@/components/Reader/hooks'

function touch(clientX: number, clientY: number) {
  return { clientX, clientY, identifier: 0, target: document.body }
}

describe('usePinchZoom', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function setup() {
    const element = document.createElement('div')
    document.body.appendChild(element)
    const elementRef = { current: element }
    const onDoubleTapDetected = vi.fn()
    const hook = renderHook(() => usePinchZoom(elementRef, 1, onDoubleTapDetected))

    return { element, onDoubleTapDetected, ...hook }
  }

  function swipe(element: HTMLElement, fromX: number, toX: number) {
    fireEvent.touchStart(element, { touches: [touch(fromX, 100)] })
    fireEvent.touchMove(element, { touches: [touch(toX, 100)] })
    fireEvent.touchEnd(element, {
      touches: [],
      changedTouches: [touch(toX, 100)],
    })
  }

  function tap(element: HTMLElement, x: number, y: number) {
    fireEvent.touchStart(element, { touches: [touch(x, y)] })
    fireEvent.touchEnd(element, {
      touches: [],
      changedTouches: [touch(x, y)],
    })
  }

  it('does not treat rapid opposite swipes as a double tap', () => {
    const { element, onDoubleTapDetected, result, unmount } = setup()

    swipe(element, 240, 80)
    act(() => vi.advanceTimersByTime(100))
    swipe(element, 80, 240)

    expect(onDoubleTapDetected).not.toHaveBeenCalled()
    expect(result.current.isZoomed).toBe(false)
    expect(result.current.scale).toBe(1)

    unmount()
    element.remove()
  })

  it('zooms after two nearby stationary taps', () => {
    const { element, onDoubleTapDetected, result, unmount } = setup()

    tap(element, 100, 120)
    act(() => vi.advanceTimersByTime(200))
    tap(element, 106, 124)

    expect(onDoubleTapDetected).toHaveBeenCalledTimes(1)
    expect(result.current.isZoomed).toBe(true)
    expect(result.current.scale).toBe(2)

    unmount()
    element.remove()
  })

  it('does not treat distant taps as a double tap', () => {
    const { element, onDoubleTapDetected, result, unmount } = setup()

    tap(element, 50, 100)
    act(() => vi.advanceTimersByTime(200))
    tap(element, 180, 100)

    expect(onDoubleTapDetected).not.toHaveBeenCalled()
    expect(result.current.isZoomed).toBe(false)

    unmount()
    element.remove()
  })
})
