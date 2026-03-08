'use client'
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type { ReaderState, ReaderAction, ReaderImage, ViewMode, ScaleMode, ReadingDirection, ReaderSettings } from './types'
import { DEFAULT_READER_SETTINGS } from './types'
import { api } from '@/lib/api'

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
  if (val === 'ltr' || val === 'rtl' || val === 'ttb') return val
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

  const setScaleMode = useCallback((mode: ScaleMode) => dispatch({ type: 'SET_SCALE_MODE', mode }), [])

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
// Core feature: serialised prefetch control

export function useSequentialPrefetch(
  images: ReaderImage[],
  currentPage: number,
  isProxyMode: boolean,
): Set<number> {
  const [prefetched, setPrefetched] = useState<Set<number>>(new Set())
  const inflightRef = useRef(false)
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
        // Proxy mode: strict 1-at-a-time — never start while another is in flight
        if (inflightRef.current) return
        inflightRef.current = true

        const capturedEpoch = epochRef.current // snapshot epoch for this request

        const el = new window.Image()
        activeImagesRef.current.add(el)
        el.onload = el.onerror = () => {
          cleanupImage(el)

          // If unmounted or the user has moved to a different page since this
          // request was started, abandon the chain.
          if (unmountedRef.current || capturedEpoch !== epochRef.current) return

          prefetchedRef.current = new Set([...prefetchedRef.current, pageNum])
          setPrefetched(new Set(prefetchedRef.current))
          inflightRef.current = false
          // Chain: immediately try the next page
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
    // Reset inflight flag so the new chain can start immediately even if the
    // old request hasn't fired its callback yet.
    inflightRef.current = false
    // Clean up any in-flight Image objects from the previous page
    cleanupAllImages()

    if (isProxyMode) {
      // Start sequential chain from current+1
      prefetchPage(currentPage + 1)
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
      // Only trigger if horizontal swipe dominates
      if (Math.abs(dx) > threshold && Math.abs(dx) > Math.abs(dy)) {
        if (dx < 0) onSwipeLeft()
        else onSwipeRight()
      }
    }

    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchend', onEnd, { passive: true })
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchend', onEnd)
    }
  }, [elementRef, onSwipeLeft, onSwipeRight, threshold, isDisabled])
}

// ── useKeyboardNav ────────────────────────────────────────────────────

export function useKeyboardNav(
  onNext: () => void,
  onPrev: () => void,
  readingDirection: ReadingDirection = 'ltr',
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
          e.preventDefault()
          onPrev()
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onNext, onPrev, readingDirection])
}

// ── useProgressSave ───────────────────────────────────────────────────

export function useProgressSave(galleryId: number, currentPage: number) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const retryRef = useRef<ReturnType<typeof setTimeout>>()

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
  overlayVisible: boolean,
) {
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [countdown, setCountdown] = useState<number>(intervalSeconds)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // Reset countdown when page changes or interval changes
  useEffect(() => {
    setCountdown(intervalSeconds)
  }, [intervalSeconds])

  useEffect(() => {
    if (!enabled || isLastPage || overlayVisible) {
      clearTimer()
      setCountdown(intervalSeconds)
      return
    }

    setCountdown(intervalSeconds)

    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          nextPage()
          return intervalSeconds
        }
        return prev - 1
      })
    }, 1000)

    return clearTimer
  }, [enabled, intervalSeconds, isLastPage, overlayVisible, nextPage, clearTimer])

  // Reset countdown on manual page change (called externally)
  const resetCountdown = useCallback(() => {
    setCountdown(intervalSeconds)
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

export function usePinchZoom(elementRef: React.RefObject<HTMLElement | null>) {
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
        isPinchingRef.current = true
        lastTouchDistRef.current = getTouchDist(e.touches)
        lastTouchCenterRef.current = getTouchCenter(e.touches)
        panStartRef.current = null
      } else if (e.touches.length === 1 && stateRef.current.isZoomed) {
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
          // If scale settled close to 1, reset
          if (stateRef.current.scale < 1.05) {
            resetZoom()
          }
          return
        }
      }

      if (e.touches.length === 0) {
        panStartRef.current = null
      }
    }

    const onDoubleTap = (e: TouchEvent) => {
      const now = Date.now()
      if (now - lastTapRef.current < 300) {
        e.preventDefault()
        resetZoom()
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

  return { ...zoomState, transform, resetZoom }
}
