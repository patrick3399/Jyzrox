'use client'
import { useEffect } from 'react'

// ── useViewportHeight ─────────────────────────────────────────────────

/**
 * Pin a container's height to the visual viewport on iOS.
 * Falls back to CSS 100dvh when visualViewport API is unavailable.
 *
 * NOTE: Currently unused. The reader-container height is locked to
 * window.innerHeight at mount time (in the Reader component) to prevent
 * iOS 15+ layout viewport shrink when the browser toolbar appears.
 * Kept here in case dynamic height adjustment is needed in future.
 */
export function useViewportHeight(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current
    if (!el) return

    const vv = window.visualViewport
    if (!vv) return // CSS dvh handles it on non-supporting browsers

    const update = () => {
      el.style.height = `${vv.height}px`
      // On iOS Safari, ensure the window isn't scrolled behind the fixed reader
      if (window.scrollY !== 0) {
        window.scrollTo(0, 0)
      }
    }

    update()
    vv.addEventListener('resize', update)
    return () => {
      vv.removeEventListener('resize', update)
    }
  }, [ref])
}
