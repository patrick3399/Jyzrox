'use client'
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type {
  ReaderState,
  ReaderAction,
  ReaderImage,
  ViewMode,
  ScaleMode,
  ReadingDirection,
  ReaderSettings,
} from './types'
import { DEFAULT_READER_SETTINGS } from './types'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'

// ── localStorage helpers ───────────────────────────────────────────────

export function loadReaderSettings(): ReaderSettings {
  if (typeof window === 'undefined') return DEFAULT_READER_SETTINGS
  try {
    const raw = localStorage.getItem('reader_settings')
    if (!raw) return DEFAULT_READER_SETTINGS
    return { ...DEFAULT_READER_SETTINGS, ...JSON.parse(raw) }
  } catch {
    return DEFAULT_READER_SETTINGS
  }
}

export function saveReaderSettings(settings: Partial<ReaderSettings>) {
  if (typeof window === 'undefined') return
  const current = loadReaderSettings()
  localStorage.setItem('reader_settings', JSON.stringify({ ...current, ...settings }))
}

function loadDirection(galleryId: number): ReadingDirection | null {
  if (typeof window === 'undefined') return null
  const val = localStorage.getItem(`reader_direction_${galleryId}`)
  if (val === 'ltr' || val === 'rtl' || val === 'vertical') return val
  return null
}

function saveDirection(galleryId: number, dir: ReadingDirection) {
  if (typeof window === 'undefined') return
  localStorage.setItem(`reader_direction_${galleryId}`, dir)
}

// ── useReaderState ────────────────────────────────────────────────────

function readerReducer(state: ReaderState, action: ReaderAction): ReaderState {
  switch (action.type) {
    case 'SET_PAGE':
      return { ...state, currentPage: action.page }
    case 'SET_VIEW_MODE':
      return { ...state, viewMode: action.mode }
    case 'TOGGLE_OVERLAY':
      return { ...state, showOverlay: !state.showOverlay }
    case 'SHOW_OVERLAY':
      return { ...state, showOverlay: true }
    case 'HIDE_OVERLAY':
      return { ...state, showOverlay: false }
    case 'SET_SCALE_MODE':
      return { ...state, scaleMode: action.mode }
    case 'SET_READING_DIRECTION':
      return { ...state, readingDirection: action.direction }
    default:
      return state
  }
}

export function useReaderState(initialPage: number, totalPages: number, galleryId: number) {
  const settings = loadReaderSettings()
  const savedDirection = loadDirection(galleryId)

  const [state, dispatch] = useReducer(readerReducer, {
    currentPage: initialPage,
    viewMode: settings.defaultViewMode,
    showOverlay: false,
    scaleMode: settings.defaultScaleMode,
    readingDirection: savedDirection ?? settings.defaultReadingDirection,
  } as ReaderState)

  const setPage = useCallback(
    (page: number) => {
      const clamped = Math.max(1, Math.min(totalPages, page))
      dispatch({ type: 'SET_PAGE', page: clamped })
    },
    [totalPages],
  )

  const nextPage = useCallback(() => setPage(state.currentPage + 1), [state.currentPage, setPage])

  const prevPage = useCallback(() => setPage(state.currentPage - 1), [state.currentPage, setPage])

  const setViewMode = useCallback((mode: ViewMode) => dispatch({ type: 'SET_VIEW_MODE', mode }), [])

  const toggleOverlay = useCallback(() => dispatch({ type: 'TOGGLE_OVERLAY' }), [])

  const setScaleMode = useCallback(
    (mode: ScaleMode) => dispatch({ type: 'SET_SCALE_MODE', mode }),
    [],
  )

  const setReadingDirection = useCallback(
    (direction: ReadingDirection) => {
      dispatch({ type: 'SET_READING_DIRECTION', direction })
      saveDirection(galleryId, direction)
    },
    [galleryId],
  )

  return {
    state,
    setPage,
    nextPage,
    prevPage,
    setViewMode,
    toggleOverlay,
    setScaleMode,
    setReadingDirection,
  }
}

// ── useSequentialPrefetch ─────────────────────────────────────────────
// Core feature: prefetch control with parallel slots + per-image timeout

/** Max concurrent in-flight prefetch requests in proxy mode */
const PROXY_PREFETCH_CONCURRENCY = 2
/** Timeout (ms) per image in proxy mode before giving up and moving on */
const PROXY_PREFETCH_TIMEOUT_MS = 2000

export function useSequentialPrefetch(
  images: ReaderImage[],
  currentPage: number,
  isProxyMode: boolean,
): Set<number> {
  const [prefetched, setPrefetched] = useState<Set<number>>(new Set())
  // Number of requests currently in flight (proxy mode)
  const inflightCountRef = useRef(0)
  const prefetchedRef = useRef<Set<number>>(new Set())
  // Track active Image elements for cleanup on unmount / page change
  const activeImagesRef = useRef<Set<HTMLImageElement>>(new Set())
  const unmountedRef = useRef(false)

  // prefetchPage needs a stable reference so we use useRef to break the
  // circular dependency with the chain callback.
  const prefetchPageRef = useRef<(pageNum: number) => void>(() => undefined)

  // Epoch: incremented on every currentPage change.
  // Each in-flight callback captures its epoch; if it doesn't match the
  // current epoch by the time it fires, it was started for a stale page
  // position and must not continue the chain.
  const epochRef = useRef(0)

  // Cleanup helper: detach handlers and stop loading
  const cleanupImage = useCallback((el: HTMLImageElement) => {
    el.onload = null
    el.onerror = null
    el.src = ''
    activeImagesRef.current.delete(el)
  }, [])

  // Cleanup all active images (used on unmount and epoch change)
  const cleanupAllImages = useCallback(() => {
    activeImagesRef.current.forEach((el) => {
      el.onload = null
      el.onerror = null
      el.src = ''
    })
    activeImagesRef.current.clear()
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      unmountedRef.current = true
      cleanupAllImages()
    }
  }, [cleanupAllImages])

  const prefetchPage = useCallback(
    (pageNum: number) => {
      const img = images.find((i) => i.pageNum === pageNum)
      if (!img || prefetchedRef.current.has(pageNum)) return

      if (isProxyMode) {
        // Proxy mode: allow up to PROXY_PREFETCH_CONCURRENCY concurrent requests.
        // Each request has a timeout; on timeout it is treated as done and the
        // chain continues to the next page so a slow image never blocks the queue.
        if (inflightCountRef.current >= PROXY_PREFETCH_CONCURRENCY) return

        inflightCountRef.current += 1
        const capturedEpoch = epochRef.current

        const el = new window.Image()
        activeImagesRef.current.add(el)

        // Timeout: if image hasn't loaded within threshold, skip and continue chain
        const timeoutId = setTimeout(() => {
          cleanupImage(el)
          if (unmountedRef.current || capturedEpoch !== epochRef.current) return
          inflightCountRef.current = Math.max(0, inflightCountRef.current - 1)
          // Skip this page (don't add to prefetched) and try next
          prefetchPageRef.current(pageNum + 1)
        }, PROXY_PREFETCH_TIMEOUT_MS)

        el.onload = el.onerror = () => {
          clearTimeout(timeoutId)
          cleanupImage(el)

          // If unmounted or the user has moved to a different page since this
          // request was started, abandon the chain.
          if (unmountedRef.current || capturedEpoch !== epochRef.current) return

          prefetchedRef.current = new Set([...prefetchedRef.current, pageNum])
          setPrefetched(new Set(prefetchedRef.current))
          inflightCountRef.current = Math.max(0, inflightCountRef.current - 1)
          // Chain: immediately try the next page in sequence
          prefetchPageRef.current(pageNum + 1)
        }
        el.src = img.url
      } else {
        // Local mode: fire-and-forget (concurrent, up to 3 ahead from caller)
        const el = new window.Image()
        activeImagesRef.current.add(el)
        el.onload = el.onerror = () => {
          cleanupImage(el)
          if (unmountedRef.current) return

          prefetchedRef.current = new Set([...prefetchedRef.current, pageNum])
          setPrefetched(new Set(prefetchedRef.current))
        }
        el.src = img.url
      }
    },
    [images, isProxyMode, cleanupImage],
  )

  // Keep the ref in sync with the latest callback
  useEffect(() => {
    prefetchPageRef.current = prefetchPage
  }, [prefetchPage])

  useEffect(() => {
    // Advance epoch so any stale in-flight callback from the previous page
    // will detect a mismatch and abort its chain.
    epochRef.current += 1
    // Reset inflight count so the new chain can start immediately even if the
    // old requests haven't fired their callbacks yet.
    inflightCountRef.current = 0
    // Clean up any in-flight Image objects from the previous page
    cleanupAllImages()

    if (isProxyMode) {
      // Start parallel prefetch chains — fire PROXY_PREFETCH_CONCURRENCY starting
      // pages so we have multiple requests in flight without strict serialisation.
      for (let slot = 0; slot < PROXY_PREFETCH_CONCURRENCY; slot++) {
        prefetchPage(currentPage + 1 + slot)
      }
    } else {
      // Local: prefetch current+1, current+2, current+3 concurrently
      for (let i = 1; i <= 3; i++) {
        prefetchPage(currentPage + i)
      }
    }
  }, [currentPage, prefetchPage, isProxyMode, cleanupAllImages])

  return prefetched
}

// ── useTouchGesture ───────────────────────────────────────────────────

export function useTouchGesture(
  elementRef: React.RefObject<HTMLElement | null>,
  onSwipeLeft: () => void,
  onSwipeRight: () => void,
  onSwipeUp?: () => void,
  threshold = 50,
  isDisabled?: () => boolean,
) {
  const startX = useRef(0)
  const startY = useRef(0)

  useEffect(() => {
    const el = elementRef.current
    if (!el) return

    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      startX.current = e.touches[0].clientX
      startY.current = e.touches[0].clientY
    }

    const onEnd = (e: TouchEvent) => {
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

    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchend', onEnd, { passive: true })
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchend', onEnd)
    }
  }, [elementRef, onSwipeLeft, onSwipeRight, onSwipeUp, threshold, isDisabled])
}

// ── useKeyboardNav ────────────────────────────────────────────────────

export function useKeyboardNav(
  onNext: () => void,
  onPrev: () => void,
  readingDirection: ReadingDirection = 'ltr',
  viewMode?: string,
) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) return
      const isRtl = readingDirection === 'rtl'
      switch (e.key) {
        case 'ArrowRight':
        case 'd':
          e.preventDefault()
          isRtl ? onPrev() : onNext()
          break
        case 'ArrowLeft':
        case 'a':
          e.preventDefault()
          isRtl ? onNext() : onPrev()
          break
        case 'ArrowDown':
          e.preventDefault()
          onNext()
          break
        case 'ArrowUp':
          // In webtoon mode (or when viewMode is not specified), ArrowUp scrolls prev
          // In single/double page mode, ArrowUp is reserved for back navigation
          if (viewMode === 'webtoon' || viewMode === undefined) {
            e.preventDefault()
            onPrev()
          }
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onNext, onPrev, readingDirection, viewMode])
}

// ── useProgressSave ───────────────────────────────────────────────────

export function useProgressSave(galleryId: number, currentPage: number) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const retryRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    // Skip progress save for proxy-only browsing (galleryId === 0)
    if (!galleryId) return

    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      api.library.saveProgress(galleryId, currentPage).catch((err) => {
        console.warn('[Reader] Failed to save progress, retrying in 5s:', err)
        clearTimeout(retryRef.current)
        retryRef.current = setTimeout(() => {
          api.library.saveProgress(galleryId, currentPage).catch((retryErr) => {
            console.warn('[Reader] Progress save retry also failed:', retryErr)
            toast.error(t('reader.progressSaveFailed'))
          })
        }, 5000)
      })
    }, 2000) // debounce 2 s

    return () => {
      clearTimeout(timerRef.current)
      clearTimeout(retryRef.current)
    }
  }, [galleryId, currentPage])
}

// ── useAutoAdvance ────────────────────────────────────────────────────

export function useAutoAdvance(
  enabled: boolean,
  intervalSeconds: number,
  nextPage: () => void,
  isLastPage: boolean,
) {
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const [countdown, setCountdown] = useState<number>(intervalSeconds)
  const nextPageRef = useRef(nextPage)
  const countdownRef = useRef(intervalSeconds)

  // Always keep ref up to date without affecting the interval effect
  useEffect(() => {
    nextPageRef.current = nextPage
  }, [nextPage])

  const clearTimer = useCallback(() => {
    if (timerRef.current !== undefined) {
      clearInterval(timerRef.current)
      timerRef.current = undefined
    }
  }, [])

  // Reset countdown when interval changes
  useEffect(() => {
    setCountdown(intervalSeconds)
  }, [intervalSeconds])

  useEffect(() => {
    if (!enabled || isLastPage) {
      clearTimer()
      setCountdown(intervalSeconds)
      countdownRef.current = intervalSeconds
      return
    }

    setCountdown(intervalSeconds)
    countdownRef.current = intervalSeconds

    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        const next = prev <= 1 ? intervalSeconds : prev - 1
        return next
      })
      countdownRef.current -= 1
      if (countdownRef.current <= 0) {
        countdownRef.current = intervalSeconds
        nextPageRef.current()
      }
    }, 1000)

    return clearTimer
  }, [enabled, intervalSeconds, isLastPage, clearTimer])

  // Reset countdown on manual page change (called externally)
  const resetCountdown = useCallback(() => {
    setCountdown(intervalSeconds)
    countdownRef.current = intervalSeconds
  }, [intervalSeconds])

  return { countdown, resetCountdown }
}

// ── useStatusBarClock ─────────────────────────────────────────────────

export function useStatusBarClock(enabled: boolean): string {
  const [time, setTime] = useState('')

  useEffect(() => {
    if (!enabled) return

    const update = () => {
      const now = new Date()
      const h = now.getHours().toString().padStart(2, '0')
      const m = now.getMinutes().toString().padStart(2, '0')
      setTime(`${h}:${m}`)
    }

    update()

    // Align to next minute boundary, then tick every 60s
    const now = new Date()
    const msUntilNextMinute = (60 - now.getSeconds()) * 1000 - now.getMilliseconds()
    let intervalId: ReturnType<typeof setInterval> | null = null

    const timeoutId = setTimeout(() => {
      update()
      intervalId = setInterval(update, 60_000)
    }, msUntilNextMinute)

    return () => {
      clearTimeout(timeoutId)
      if (intervalId !== null) clearInterval(intervalId)
    }
  }, [enabled])

  return time
}

// ── usePinchZoom ──────────────────────────────────────────────────────

interface PinchZoomState {
  scale: number
  translateX: number
  translateY: number
  isZoomed: boolean
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
  const lastTapRef = useRef<number>(0)
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
  useEffect(() => { onDoubleTapDetectedRef.current = onDoubleTapDetected }, [onDoubleTapDetected])

  const resetTriggerInitRef = useRef(true)
  useEffect(() => {
    if (resetTriggerInitRef.current) {
      resetTriggerInitRef.current = false
      return
    }
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
        setIsGesturing(true)
        isPinchingRef.current = true
        lastTouchDistRef.current = getTouchDist(e.touches)
        lastTouchCenterRef.current = getTouchCenter(e.touches)
        panStartRef.current = null
      } else if (e.touches.length === 1 && stateRef.current.isZoomed) {
        setIsGesturing(true)
        panStartRef.current = {
          x: e.touches[0].clientX,
          y: e.touches[0].clientY,
          tx: stateRef.current.translateX,
          ty: stateRef.current.translateY,
        }
      }
    }

    const onTouchMove = (e: TouchEvent) => {
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
    }

    const onDoubleTap = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      const now = Date.now()
      if (now - lastTapRef.current < 300) {
        e.preventDefault()
        onDoubleTapDetectedRef.current?.()
        if (stateRef.current.isZoomed) {
          resetZoom()
        } else {
          // Zoom to 2× centered on the tapped point
          const touch = e.touches[0]
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
      lastTapRef.current = now
    }

    el.addEventListener('touchstart', onTouchStart, { passive: false })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
    el.addEventListener('touchstart', onDoubleTap, { passive: false })

    return () => {
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
      el.removeEventListener('touchstart', onDoubleTap)
    }
  }, [elementRef, clampTranslate, resetZoom])

  const transform = `scale(${zoomState.scale}) translate(${zoomState.translateX / zoomState.scale}px, ${zoomState.translateY / zoomState.scale}px)`

  return { ...zoomState, transform, resetZoom, isGesturing }
}

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
