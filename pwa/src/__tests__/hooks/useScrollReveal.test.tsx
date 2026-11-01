/**
 * Library search block: hide on scroll down, reveal on scroll up.
 *
 * The block is `position: sticky`; the hook only decides whether the stuck
 * block is slid out of view. A zero-height sentinel marks the block's natural
 * position, so "stuck" means the sentinel has scrolled above the sticky top.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useScrollReveal } from '@/hooks/useScrollReveal'

let sentinelTop = 100

function makeRefs() {
  const sentinel = document.createElement('div')
  sentinel.getBoundingClientRect = () => ({ top: sentinelTop }) as DOMRect
  const block = document.createElement('div')
  return { sentinelRef: { current: sentinel }, blockRef: { current: block } }
}

function scrollTo(y: number) {
  // The sentinel moves up exactly as far as the page scrolls.
  sentinelTop = 100 - y
  Object.defineProperty(window, 'scrollY', { value: y, configurable: true })
  act(() => {
    window.dispatchEvent(new Event('scroll'))
  })
}

beforeEach(() => {
  sentinelTop = 100
  Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
    cb(0)
    return 0
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useScrollReveal', () => {
  it('test_block_is_visible_and_not_stuck_at_the_top_of_the_page', () => {
    const refs = makeRefs()
    const { result } = renderHook(() => useScrollReveal({ ...refs, locked: false }))

    expect(result.current).toMatchObject({ stuck: false, hidden: false })
  })

  it('test_scrolling_down_past_the_block_hides_it', () => {
    const refs = makeRefs()
    const { result } = renderHook(() => useScrollReveal({ ...refs, locked: false }))

    scrollTo(200)
    scrollTo(400)

    expect(result.current).toMatchObject({ stuck: true, hidden: true })
  })

  it('test_scrolling_up_after_scrolling_down_reveals_the_stuck_block', () => {
    const refs = makeRefs()
    const { result } = renderHook(() => useScrollReveal({ ...refs, locked: false }))

    scrollTo(400)
    scrollTo(800)
    scrollTo(760)

    expect(result.current).toMatchObject({ stuck: true, hidden: false })
  })

  it('test_tiny_scroll_jitter_below_the_threshold_does_not_toggle_the_block', () => {
    const refs = makeRefs()
    const { result } = renderHook(() => useScrollReveal({ ...refs, locked: false }))

    scrollTo(400)
    scrollTo(800)
    scrollTo(797)

    expect(result.current.hidden).toBe(true)
  })

  it('test_scrolling_down_while_the_block_is_still_in_its_natural_place_does_not_hide_it', () => {
    const refs = makeRefs()
    const { result } = renderHook(() => useScrollReveal({ ...refs, locked: false }))

    scrollTo(50)

    expect(result.current).toMatchObject({ stuck: false, hidden: false })
  })

  it('test_locked_block_stays_visible_while_scrolling_down', () => {
    // Search input focused or filter panel open: never slide it away.
    const refs = makeRefs()
    const { result } = renderHook(() => useScrollReveal({ ...refs, locked: true }))

    scrollTo(400)
    scrollTo(800)

    expect(result.current).toMatchObject({ stuck: true, hidden: false })
  })

  it('test_returning_to_the_top_unsticks_and_shows_the_block', () => {
    const refs = makeRefs()
    const { result } = renderHook(() => useScrollReveal({ ...refs, locked: false }))

    scrollTo(800)
    scrollTo(0)

    expect(result.current).toMatchObject({ stuck: false, hidden: false })
  })

  it('test_rebase_after_a_large_downward_jump_while_locked_leaves_the_block_visible_once_unlocked', () => {
    // A layout switch locks the bar, then lands with a programmatic jump down.
    // Without rebase() the jump is read as the user scrolling down and hides
    // the bar the moment the lock releases.
    const refs = makeRefs()
    const { result, rerender } = renderHook(
      ({ locked }) => useScrollReveal({ ...refs, locked }),
      { initialProps: { locked: false } },
    )
    scrollTo(300)
    scrollTo(280)
    expect(result.current.hidden).toBe(false)

    rerender({ locked: true })
    scrollTo(5000)
    act(() => {
      result.current.rebase()
    })
    rerender({ locked: false })

    expect(result.current).toMatchObject({ stuck: true, hidden: false })

    // A later genuine scroll down still hides it: rebase only re-zeroes tracking.
    scrollTo(5200)
    expect(result.current.hidden).toBe(true)
  })

  it('test_without_rebase_the_same_downward_jump_hides_the_block_once_unlocked', () => {
    // Control for the test above: pins that the jump alone is what hides it.
    const refs = makeRefs()
    const { result, rerender } = renderHook(
      ({ locked }) => useScrollReveal({ ...refs, locked }),
      { initialProps: { locked: true } },
    )
    scrollTo(300)
    scrollTo(5000)
    rerender({ locked: false })

    expect(result.current.hidden).toBe(true)
  })
})
