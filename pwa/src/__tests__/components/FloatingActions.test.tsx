import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  usePathname: () => '/library/twitter/12345',
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { FloatingActions } from '@/components/FloatingActions'

function setScrollY(value: number) {
  Object.defineProperty(window, 'scrollY', { value, writable: true, configurable: true })
}

describe('FloatingActions — scroll to top on virtualized pages', () => {
  let scrollToSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    scrollToSpy = vi.fn()
    // jsdom has no real scrollTo; stub it and never let it mutate scrollY so we
    // can simulate a reflow-cancelled smooth scroll that never reaches the top.
    window.scrollTo = scrollToSpy as unknown as typeof window.scrollTo
    setScrollY(600)
  })

  afterEach(() => {
    vi.useRealTimers()
    setScrollY(0)
  })

  it('test_scrollTop_reasserts_when_smooth_scroll_stalls_above_top', () => {
    // Regression: on a long window-virtualized list, rows re-measure as they
    // enter the viewport and reflow the document, cancelling the in-flight
    // smooth scroll before it reaches y=0 — the page stalls partway ("捲不動").
    render(<FloatingActions />)

    // scrollY (600) > 300 → the scroll-to-top FAB is shown.
    const btn = screen.getByRole('button', { name: 'common.scrollToTop' })
    fireEvent.click(btn)

    // First attempt is the (smooth) scroll.
    expect(scrollToSpy).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    scrollToSpy.mockClear()

    // Smooth scroll was cancelled by reflow: still not at the top.
    setScrollY(420)
    act(() => {
      vi.runAllTimers()
    })

    // The fix re-asserts the top so the page actually lands at 0.
    expect(scrollToSpy).toHaveBeenCalledWith({ top: 0, behavior: 'auto' })
  })

  it('test_scrollTop_does_not_snap_when_smooth_scroll_already_reached_top', () => {
    render(<FloatingActions />)
    const btn = screen.getByRole('button', { name: 'common.scrollToTop' })
    fireEvent.click(btn)
    scrollToSpy.mockClear()

    // Smooth scroll completed on its own: we are at the top.
    setScrollY(0)
    act(() => {
      vi.runAllTimers()
    })

    // No corrective jump needed — the smooth animation is preserved.
    expect(scrollToSpy).not.toHaveBeenCalled()
  })
})
