'use client'

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

interface UseScrollRevealOptions {
  /** Zero-height marker placed right before the sticky block (its natural position). */
  sentinelRef: RefObject<HTMLElement | null>
  /** The `position: sticky` block; its computed `top` is the stuck offset. */
  blockRef: RefObject<HTMLElement | null>
  /** Keep the block visible (input focused, panel open). */
  locked: boolean
  /** Scroll distance (px) needed to flip direction; filters jitter and rubber-band. */
  threshold?: number
}

/**
 * Hide-on-scroll-down / reveal-on-scroll-up for a sticky block. The block stays
 * in normal flow (sticky + transform), so the grid below keeps its offsetTop and
 * scroll restore is unaffected.
 */
export function useScrollReveal({
  sentinelRef,
  blockRef,
  locked,
  threshold = 6,
}: UseScrollRevealOptions): { stuck: boolean; hidden: boolean; rebase: () => void } {
  const [state, setState] = useState({ stuck: false, down: false })
  const lastYRef = useRef(0)

  useEffect(() => {
    let scheduled = false
    let frame = 0
    lastYRef.current = window.scrollY

    const update = () => {
      scheduled = false
      const sentinel = sentinelRef.current
      if (!sentinel) return
      const block = blockRef.current
      const stickyTop = block ? parseFloat(getComputedStyle(block).top) || 0 : 0
      const stuck = sentinel.getBoundingClientRect().top < stickyTop

      const y = window.scrollY
      const dy = y - lastYRef.current
      setState((prev) => {
        let down = prev.down
        if (!stuck) down = false
        else if (Math.abs(dy) >= threshold) down = dy > 0
        return prev.stuck === stuck && prev.down === down ? prev : { stuck, down }
      })
      // Only move the reference point once the movement counts, so a slow
      // scroll still accumulates past the threshold.
      if (!stuck || Math.abs(dy) >= threshold) lastYRef.current = y
    }

    const onScroll = () => {
      // Flag before scheduling: a frame callback that runs synchronously must
      // not be undone by the assignment of its own id.
      if (scheduled) return
      scheduled = true
      frame = requestAnimationFrame(update)
    }

    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (scheduled) cancelAnimationFrame(frame)
    }
  }, [sentinelRef, blockRef, threshold])

  // Re-zero the direction tracking after a programmatic jump so it never reads
  // as the user scrolling down.
  const rebase = useCallback(() => {
    lastYRef.current = window.scrollY
    setState((prev) => (prev.down ? { ...prev, down: false } : prev))
  }, [])

  return { stuck: state.stuck, hidden: !locked && state.stuck && state.down, rebase }
}
