'use client'
import { useRef, useCallback } from 'react'

interface UseLongPressOptions {
  threshold?: number      // ms, default 500
  moveThreshold?: number  // px, default 10
  onLongPress: (e: React.TouchEvent | React.MouseEvent) => void
}

export function useLongPress({ threshold = 500, moveThreshold = 10, onLongPress }: UseLongPressOptions) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const startPosRef = useRef<{ x: number; y: number } | null>(null)
  const firedRef = useRef(false)

  const cancel = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    startPosRef.current = null
  }, [])

  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      firedRef.current = false
      const touch = e.touches[0]
      startPosRef.current = { x: touch.clientX, y: touch.clientY }
      timerRef.current = setTimeout(() => {
        firedRef.current = true
        onLongPress(e)
        timerRef.current = null
      }, threshold)
    },
    [threshold, onLongPress],
  )

  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!startPosRef.current) return
      const touch = e.touches[0]
      const dx = touch.clientX - startPosRef.current.x
      const dy = touch.clientY - startPosRef.current.y
      if (Math.sqrt(dx * dx + dy * dy) > moveThreshold) {
        cancel()
      }
    },
    [moveThreshold, cancel],
  )

  const onTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      if (firedRef.current) {
        // Prevent the browser from generating a synthetic click event
        // after a successful long-press, which would trigger onClick.
        // This also prevents phantom clicks on context menu items that
        // appeared under the finger during the long-press.
        e.preventDefault()
      }
      cancel()
      // Reset AFTER the preventDefault check so that when the browser fires
      // contextmenu (step 3) before touchend (step 4), onContextMenu does not
      // clear firedRef prematurely and cause touchend to skip preventDefault.
      firedRef.current = false
    },
    [cancel],
  )

  const onContextMenu = useCallback(
    (e: React.MouseEvent) => {
      // On desktop, right-click triggers onLongPress and suppresses the native menu.
      // On touch devices, the browser fires contextmenu after a long-press; we
      // already fired via the timer, so just suppress it.
      e.preventDefault()
      if (!firedRef.current) {
        onLongPress(e)
      }
      // Do NOT reset firedRef here. On touch devices the sequence is:
      //   touchstart → timer fires (firedRef=true) → contextmenu → touchend
      // Resetting here would cause touchend to see firedRef=false and skip
      // preventDefault, letting the browser generate a synthetic click that
      // hits the context menu item now positioned under the finger.
      // onTouchEnd is responsible for resetting firedRef after preventDefault.
      // On desktop there is no touchstart/touchend, so firedRef is never set
      // to true by the timer and the check above (!firedRef.current) always
      // passes — no reset needed here either.
    },
    [onLongPress],
  )

  return { onTouchStart, onTouchMove, onTouchEnd, onContextMenu }
}
