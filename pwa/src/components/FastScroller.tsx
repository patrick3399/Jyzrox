'use client'
import { useState, useRef, useCallback, useEffect } from 'react'

interface FastScrollerProps {
  totalHeight: number
  visible: boolean
}

const THUMB_HEIGHT = 48
const HIDE_DELAY_MS = 1500

export function FastScroller({ totalHeight, visible }: FastScrollerProps) {
  const [show, setShow] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [thumbTop, setThumbTop] = useState(0)

  const trackRef = useRef<HTMLDivElement>(null)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dragStartYRef = useRef(0)
  const dragStartScrollYRef = useRef(0)

  // Compute thumb top from current scroll position
  const computeThumbTop = useCallback(() => {
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight
    if (maxScroll <= 0) return 0
    const trackEl = trackRef.current
    if (!trackEl) return 0
    const trackHeight = trackEl.clientHeight
    const ratio = window.scrollY / maxScroll
    return ratio * (trackHeight - THUMB_HEIGHT)
  }, [])

  const scheduleHide = useCallback(() => {
    if (hideTimerRef.current !== null) clearTimeout(hideTimerRef.current)
    hideTimerRef.current = setTimeout(() => {
      if (!dragging) setShow(false)
    }, HIDE_DELAY_MS)
  }, [dragging])

  // Listen to window scroll to show/update thumb
  useEffect(() => {
    if (!visible) return

    const onScroll = () => {
      setShow(true)
      setThumbTop(computeThumbTop())
      scheduleHide()
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (hideTimerRef.current !== null) clearTimeout(hideTimerRef.current)
    }
  }, [visible, computeThumbTop, scheduleHide])

  // When dragging ends, restart the hide timer
  useEffect(() => {
    if (!dragging) {
      scheduleHide()
    } else {
      if (hideTimerRef.current !== null) clearTimeout(hideTimerRef.current)
    }
  }, [dragging, scheduleHide])

  // Keep thumbTop in sync while not dragging (e.g. after totalHeight changes)
  useEffect(() => {
    setThumbTop(computeThumbTop())
  }, [totalHeight, computeThumbTop])

  // --- Drag helpers ---
  const scrollFromClientY = useCallback((clientY: number) => {
    const trackEl = trackRef.current
    if (!trackEl) return
    const trackRect = trackEl.getBoundingClientRect()
    const trackHeight = trackEl.clientHeight
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight
    if (maxScroll <= 0) return

    // Position of the thumb centre relative to track start
    const relY = clientY - trackRect.top - THUMB_HEIGHT / 2
    const clamped = Math.max(0, Math.min(relY, trackHeight - THUMB_HEIGHT))
    const ratio = clamped / (trackHeight - THUMB_HEIGHT)
    window.scrollTo({ top: ratio * maxScroll, behavior: 'instant' })
    setThumbTop(clamped)
  }, [])

  // Mouse drag
  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setDragging(true)
      dragStartYRef.current = e.clientY
      dragStartScrollYRef.current = window.scrollY

      const onMouseMove = (ev: MouseEvent) => {
        scrollFromClientY(ev.clientY)
      }
      const onMouseUp = () => {
        setDragging(false)
        document.removeEventListener('mousemove', onMouseMove)
        document.removeEventListener('mouseup', onMouseUp)
      }
      document.addEventListener('mousemove', onMouseMove)
      document.addEventListener('mouseup', onMouseUp)
    },
    [scrollFromClientY],
  )

  // Touch drag
  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      const touch = e.touches[0]
      if (!touch) return
      setDragging(true)
      dragStartYRef.current = touch.clientY
      dragStartScrollYRef.current = window.scrollY

      const onTouchMove = (ev: TouchEvent) => {
        const t = ev.touches[0]
        if (!t) return
        scrollFromClientY(t.clientY)
      }
      const onTouchEnd = () => {
        setDragging(false)
        document.removeEventListener('touchmove', onTouchMove)
        document.removeEventListener('touchend', onTouchEnd)
      }
      document.addEventListener('touchmove', onTouchMove, { passive: true })
      document.addEventListener('touchend', onTouchEnd)
    },
    [scrollFromClientY],
  )

  if (!visible) return null

  const thumbClass = [
    'fast-scroller-thumb',
    dragging ? 'dragging' : show ? 'visible' : 'hidden',
  ].join(' ')

  return (
    /* Track: fixed right edge, full viewport height respecting safe areas */
    <div
      ref={trackRef}
      aria-hidden="true"
      style={{
        position: 'fixed',
        top: 'env(safe-area-inset-top, 0px)',
        bottom: 'env(safe-area-inset-bottom, 0px)',
        right: 'max(4px, env(safe-area-inset-right, 4px))',
        width: 16,
        zIndex: 50,
        pointerEvents: 'none',
      }}
    >
      {/* Thumb */}
      <div
        className={thumbClass}
        onMouseDown={onMouseDown}
        onTouchStart={onTouchStart}
        style={{
          position: 'absolute',
          top: thumbTop,
          right: 0,
          height: THUMB_HEIGHT,
          cursor: 'grab',
          pointerEvents: 'auto',
          userSelect: 'none',
        }}
      />
    </div>
  )
}
