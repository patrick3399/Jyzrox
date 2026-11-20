'use client'
import { useEffect, useRef } from 'react'
import type { ReadingDirection } from './types'

// ── useTouchGesture ───────────────────────────────────────────────────

export function useTouchGesture(
  elementRef: React.RefObject<HTMLElement | null>,
  onSwipeLeft: () => void,
  onSwipeRight: () => void,
  onSwipeUp?: () => void,
  threshold = 50,
  isDisabled?: () => boolean,
  /** Touches that start inside a match (scrollers, sliders) are not swipes. */
  ignoreSelector?: string,
) {
  const startX = useRef(0)
  const startY = useRef(0)
  // Only a gesture that began with exactly one finger, outside ignoreSelector,
  // and never grew a second finger is a swipe. These are native listeners on
  // the container, so a React stopPropagation() below never hides a drag.
  const trackingRef = useRef(false)

  useEffect(() => {
    const el = elementRef.current
    if (!el) return

    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) {
        // A second finger turns the gesture into a pinch for good.
        trackingRef.current = false
        return
      }
      const target = e.target as Element | null
      if (ignoreSelector && target?.closest?.(ignoreSelector)) {
        trackingRef.current = false
        return
      }
      trackingRef.current = true
      startX.current = e.touches[0].clientX
      startY.current = e.touches[0].clientY
    }

    const onEnd = (e: TouchEvent) => {
      // Wait for the last finger; a pinch's first lift is not a swipe end.
      if (e.touches.length !== 0) return
      if (!trackingRef.current) return
      trackingRef.current = false
      if (isDisabled?.()) return
      const dx = e.changedTouches[0].clientX - startX.current
      const dy = e.changedTouches[0].clientY - startY.current
      if (Math.abs(dx) > threshold && Math.abs(dx) > Math.abs(dy)) {
        // Horizontal swipe dominates → page turn
        if (dx < 0) onSwipeLeft()
        else onSwipeRight()
      } else if (onSwipeUp && dy < -threshold && Math.abs(dy) > Math.abs(dx)) {
        // Vertical swipe-up dominates → back
        onSwipeUp()
      }
    }

    const onCancel = () => {
      trackingRef.current = false
    }

    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchend', onEnd, { passive: true })
    el.addEventListener('touchcancel', onCancel, { passive: true })
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('touchcancel', onCancel)
    }
  }, [elementRef, onSwipeLeft, onSwipeRight, onSwipeUp, threshold, isDisabled, ignoreSelector])
}

// ── useKeyboardNav ────────────────────────────────────────────────────

export function useKeyboardNav(
  onNext: () => void,
  onPrev: () => void,
  onToggleOverlay: () => void,
  onBack: () => void,
  readingDirection: ReadingDirection = 'ltr',
  viewMode?: string,
) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) return
      const isWebtoon = viewMode === 'webtoon'
      const isRtl = readingDirection === 'rtl'
      switch (e.key) {
        case 'ArrowRight':
        case 'd':
          e.preventDefault()
          if (isWebtoon) {
            onNext()
          } else if (isRtl) {
            onPrev()
          } else {
            onNext()
          }
          break
        case 'ArrowLeft':
        case 'a':
          e.preventDefault()
          if (isWebtoon) {
            onPrev()
          } else if (isRtl) {
            onNext()
          } else {
            onPrev()
          }
          break
        case 'ArrowDown':
        case 's':
          e.preventDefault()
          onToggleOverlay()
          break
        case 'ArrowUp':
        case 'w':
          e.preventDefault()
          onBack()
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onNext, onPrev, onToggleOverlay, onBack, readingDirection, viewMode])
}
