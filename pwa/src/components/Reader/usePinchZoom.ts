'use client'
import { useCallback, useEffect, useRef, useState } from 'react'

// ── usePinchZoom ──────────────────────────────────────────────────────

interface PinchZoomState {
  scale: number
  translateX: number
  translateY: number
  isZoomed: boolean
}

const DOUBLE_TAP_DELAY_MS = 300
const TAP_MOVE_TOLERANCE_PX = 12
const DOUBLE_TAP_DISTANCE_PX = 40

interface TapCandidate {
  x: number
  y: number
  moved: boolean
}

interface CompletedTap {
  time: number
  x: number
  y: number
}

export function usePinchZoom(
  elementRef: React.RefObject<HTMLElement | null>,
  resetTrigger?: number,
  onDoubleTapDetected?: () => void,
) {
  const [zoomState, setZoomState] = useState<PinchZoomState>({
    scale: 1,
    translateX: 0,
    translateY: 0,
    isZoomed: false,
  })

  const stateRef = useRef(zoomState)
  useEffect(() => {
    stateRef.current = zoomState
  })

  const [isGesturing, setIsGesturing] = useState(false)
  const lastTouchDistRef = useRef<number | null>(null)
  const lastTouchCenterRef = useRef<{ x: number; y: number } | null>(null)
  const panStartRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)
  const tapCandidateRef = useRef<TapCandidate | null>(null)
  const lastTapRef = useRef<CompletedTap | null>(null)
  const isPinchingRef = useRef(false)

  const clampTranslate = useCallback(
    (scale: number, tx: number, ty: number, el: HTMLElement): { tx: number; ty: number } => {
      const rect = el.getBoundingClientRect()
      const maxTx = ((scale - 1) * rect.width) / 2
      const maxTy = ((scale - 1) * rect.height) / 2
      return {
        tx: Math.max(-maxTx, Math.min(maxTx, tx)),
        ty: Math.max(-maxTy, Math.min(maxTy, ty)),
      }
    },
    [],
  )

  const resetZoom = useCallback(() => {
    setZoomState({ scale: 1, translateX: 0, translateY: 0, isZoomed: false })
  }, [])

  // Keep callback ref stable so the touch effect doesn't re-register on every render
  const onDoubleTapDetectedRef = useRef(onDoubleTapDetected)
  useEffect(() => {
    onDoubleTapDetectedRef.current = onDoubleTapDetected
  }, [onDoubleTapDetected])

  const resetTriggerInitRef = useRef(true)
  useEffect(() => {
    if (resetTriggerInitRef.current) {
      resetTriggerInitRef.current = false
      return
    }
    tapCandidateRef.current = null
    lastTapRef.current = null
    resetZoom()
  }, [resetTrigger, resetZoom])

  useEffect(() => {
    const el = elementRef.current
    if (!el) return

    const getTouchDist = (touches: TouchList) => {
      const dx = touches[0].clientX - touches[1].clientX
      const dy = touches[0].clientY - touches[1].clientY
      return Math.sqrt(dx * dx + dy * dy)
    }

    const getTouchCenter = (touches: TouchList) => ({
      x: (touches[0].clientX + touches[1].clientX) / 2,
      y: (touches[0].clientY + touches[1].clientY) / 2,
    })

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 2) {
        tapCandidateRef.current = null
        lastTapRef.current = null
        setIsGesturing(true)
        isPinchingRef.current = true
        lastTouchDistRef.current = getTouchDist(e.touches)
        lastTouchCenterRef.current = getTouchCenter(e.touches)
        panStartRef.current = null
      } else if (e.touches.length === 1) {
        const touch = e.touches[0]
        tapCandidateRef.current = {
          x: touch.clientX,
          y: touch.clientY,
          moved: false,
        }
        if (!stateRef.current.isZoomed) return

        setIsGesturing(true)
        panStartRef.current = {
          x: touch.clientX,
          y: touch.clientY,
          tx: stateRef.current.translateX,
          ty: stateRef.current.translateY,
        }
      }
    }

    const onTouchMove = (e: TouchEvent) => {
      const tapCandidate = tapCandidateRef.current
      if (e.touches.length === 1 && tapCandidate) {
        const dx = e.touches[0].clientX - tapCandidate.x
        const dy = e.touches[0].clientY - tapCandidate.y
        if (Math.hypot(dx, dy) > TAP_MOVE_TOLERANCE_PX) {
          tapCandidate.moved = true
          lastTapRef.current = null
        }
      }

      if (e.touches.length === 2 && lastTouchDistRef.current !== null) {
        e.preventDefault()
        const newDist = getTouchDist(e.touches)
        const ratio = newDist / lastTouchDistRef.current
        const { scale: currentScale, translateX, translateY } = stateRef.current

        const newScale = Math.max(1, Math.min(5, currentScale * ratio))
        const clamped = clampTranslate(newScale, translateX, translateY, el)

        setZoomState({
          scale: newScale,
          translateX: clamped.tx,
          translateY: clamped.ty,
          isZoomed: newScale > 1.01,
        })

        lastTouchDistRef.current = newDist
      } else if (e.touches.length === 1 && panStartRef.current && stateRef.current.isZoomed) {
        e.preventDefault()
        const dx = e.touches[0].clientX - panStartRef.current.x
        const dy = e.touches[0].clientY - panStartRef.current.y
        const newTx = panStartRef.current.tx + dx
        const newTy = panStartRef.current.ty + dy
        const clamped = clampTranslate(stateRef.current.scale, newTx, newTy, el)

        setZoomState((prev) => ({
          ...prev,
          translateX: clamped.tx,
          translateY: clamped.ty,
        }))
      }
    }

    const onTouchEnd = (e: TouchEvent) => {
      if (e.touches.length < 2) {
        lastTouchDistRef.current = null
        lastTouchCenterRef.current = null

        if (isPinchingRef.current) {
          isPinchingRef.current = false
          panStartRef.current = null
          if (e.touches.length === 0) setIsGesturing(false)
          // If scale settled close to 1, reset
          if (stateRef.current.scale < 1.02) {
            resetZoom()
          }
          return
        }
      }

      if (e.touches.length === 0) {
        panStartRef.current = null
        setIsGesturing(false)
      }

      const tapCandidate = tapCandidateRef.current
      tapCandidateRef.current = null
      if (!tapCandidate || tapCandidate.moved || e.changedTouches.length !== 1) return

      const touch = e.changedTouches[0]
      const endDx = touch.clientX - tapCandidate.x
      const endDy = touch.clientY - tapCandidate.y
      if (Math.hypot(endDx, endDy) > TAP_MOVE_TOLERANCE_PX) {
        lastTapRef.current = null
        return
      }

      const now = Date.now()
      const lastTap = lastTapRef.current
      const isDoubleTap =
        lastTap !== null &&
        now - lastTap.time < DOUBLE_TAP_DELAY_MS &&
        Math.hypot(touch.clientX - lastTap.x, touch.clientY - lastTap.y) < DOUBLE_TAP_DISTANCE_PX

      if (!isDoubleTap) {
        lastTapRef.current = { time: now, x: touch.clientX, y: touch.clientY }
        return
      }

      lastTapRef.current = null
      e.preventDefault()
      onDoubleTapDetectedRef.current?.()
      if (stateRef.current.isZoomed) {
        resetZoom()
      } else {
        // Zoom to 2× centered on the tapped point
        const rect = el.getBoundingClientRect()
        const tapX = touch.clientX - rect.left - rect.width / 2
        const tapY = touch.clientY - rect.top - rect.height / 2
        const targetScale = 2
        const rawTx = (1 - targetScale) * tapX
        const rawTy = (1 - targetScale) * tapY
        const clamped = clampTranslate(targetScale, rawTx, rawTy, el)
        setZoomState({
          scale: targetScale,
          translateX: clamped.tx,
          translateY: clamped.ty,
          isZoomed: true,
        })
      }
    }

    const onTouchCancel = () => {
      tapCandidateRef.current = null
      lastTapRef.current = null
      lastTouchDistRef.current = null
      lastTouchCenterRef.current = null
      panStartRef.current = null
      isPinchingRef.current = false
      setIsGesturing(false)
    }

    el.addEventListener('touchstart', onTouchStart, { passive: false })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: false })
    el.addEventListener('touchcancel', onTouchCancel, { passive: true })

    return () => {
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
      el.removeEventListener('touchcancel', onTouchCancel)
    }
  }, [elementRef, clampTranslate, resetZoom])

  const transform = `scale(${zoomState.scale}) translate(${zoomState.translateX / zoomState.scale}px, ${zoomState.translateY / zoomState.scale}px)`

  return { ...zoomState, transform, resetZoom, isGesturing }
}
