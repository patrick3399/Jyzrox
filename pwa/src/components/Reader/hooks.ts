'use client'
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type { ReaderState, ReaderAction, ReaderImage, ViewMode } from './types'
import { api } from '@/lib/api'

// ── useReaderState ────────────────────────────────────────────────────

function readerReducer(state: ReaderState, action: ReaderAction): ReaderState {
  switch (action.type) {
    case 'SET_PAGE':
      return { ...state, currentPage: action.page }
    case 'SET_VIEW_MODE':
      return { ...state, viewMode: action.mode }
    case 'TOGGLE_FULLSCREEN':
      return { ...state, isFullscreen: !state.isFullscreen }
    case 'SET_BRIGHTNESS':
      return { ...state, brightness: Math.max(0.3, Math.min(1.0, action.value)) }
    case 'SET_BG_COLOR':
      return { ...state, bgColor: action.color }
    case 'TOGGLE_OVERLAY':
      return { ...state, showOverlay: !state.showOverlay }
    case 'SHOW_OVERLAY':
      return { ...state, showOverlay: true }
    case 'HIDE_OVERLAY':
      return { ...state, showOverlay: false }
    default:
      return state
  }
}

export function useReaderState(initialPage: number, totalPages: number) {
  const [state, dispatch] = useReducer(readerReducer, {
    currentPage: initialPage,
    viewMode: 'single',
    isFullscreen: false,
    brightness: 1.0,
    bgColor: '#000000',
    showOverlay: false,
  } as ReaderState)

  const setPage = useCallback(
    (page: number) => {
      const clamped = Math.max(1, Math.min(totalPages, page))
      dispatch({ type: 'SET_PAGE', page: clamped })
    },
    [totalPages]
  )

  const nextPage = useCallback(
    () => setPage(state.currentPage + 1),
    [state.currentPage, setPage]
  )

  const prevPage = useCallback(
    () => setPage(state.currentPage - 1),
    [state.currentPage, setPage]
  )

  const setViewMode = useCallback(
    (mode: ViewMode) => dispatch({ type: 'SET_VIEW_MODE', mode }),
    []
  )

  const toggleFullscreen = useCallback(
    () => dispatch({ type: 'TOGGLE_FULLSCREEN' }),
    []
  )

  const setBrightness = useCallback(
    (value: number) => dispatch({ type: 'SET_BRIGHTNESS', value }),
    []
  )

  const setBgColor = useCallback(
    (color: string) => dispatch({ type: 'SET_BG_COLOR', color }),
    []
  )

  const toggleOverlay = useCallback(
    () => dispatch({ type: 'TOGGLE_OVERLAY' }),
    []
  )

  return {
    state,
    setPage,
    nextPage,
    prevPage,
    setViewMode,
    toggleFullscreen,
    setBrightness,
    setBgColor,
    toggleOverlay,
  }
}

// ── useSequentialPrefetch ─────────────────────────────────────────────
// Core feature: serialised prefetch control

export function useSequentialPrefetch(
  images: ReaderImage[],
  currentPage: number,
  isProxyMode: boolean
): Set<number> {
  const [prefetched, setPrefetched] = useState<Set<number>>(new Set())
  const inflightRef = useRef(false)
  const prefetchedRef = useRef<Set<number>>(new Set())

  // prefetchPage needs a stable reference so we use useRef to break the
  // circular dependency with the chain callback.
  const prefetchPageRef = useRef<(pageNum: number) => void>(() => undefined)

  // Epoch: incremented on every currentPage change.
  // Each in-flight callback captures its epoch; if it doesn't match the
  // current epoch by the time it fires, it was started for a stale page
  // position and must not continue the chain.
  const epochRef = useRef(0)

  const prefetchPage = useCallback(
    (pageNum: number) => {
      const img = images.find((i) => i.pageNum === pageNum)
      if (!img || prefetchedRef.current.has(pageNum)) return

      if (isProxyMode) {
        // Proxy mode: strict 1-at-a-time — never start while another is in flight
        if (inflightRef.current) return
        inflightRef.current = true

        const capturedEpoch = epochRef.current   // snapshot epoch for this request

        const el = new window.Image()
        el.onload = el.onerror = () => {
          // If the user has moved to a different page since this request was
          // started, abandon the chain without touching inflightRef so the
          // new chain (already running) is not disrupted.
          if (capturedEpoch !== epochRef.current) return

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
        el.onload = el.onerror = () => {
          prefetchedRef.current = new Set([...prefetchedRef.current, pageNum])
          setPrefetched(new Set(prefetchedRef.current))
        }
        el.src = img.url
      }
    },
    [images, isProxyMode]
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

    if (isProxyMode) {
      // Start sequential chain from current+1
      prefetchPage(currentPage + 1)
    } else {
      // Local: prefetch current+1, current+2, current+3 concurrently
      for (let i = 1; i <= 3; i++) {
        prefetchPage(currentPage + i)
      }
    }
  }, [currentPage, prefetchPage, isProxyMode])

  return prefetched
}

// ── useTouchGesture ───────────────────────────────────────────────────

export function useTouchGesture(
  elementRef: React.RefObject<HTMLElement | null>,
  onSwipeLeft: () => void,
  onSwipeRight: () => void,
  threshold = 50
) {
  const startX = useRef(0)
  const startY = useRef(0)

  useEffect(() => {
    const el = elementRef.current
    if (!el) return

    const onStart = (e: TouchEvent) => {
      startX.current = e.touches[0].clientX
      startY.current = e.touches[0].clientY
    }

    const onEnd = (e: TouchEvent) => {
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
  }, [elementRef, onSwipeLeft, onSwipeRight, threshold])
}

// ── useKeyboardNav ────────────────────────────────────────────────────

export function useKeyboardNav(
  onNext: () => void,
  onPrev: () => void,
  onFullscreen: () => void
) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) return
      switch (e.key) {
        case 'ArrowRight':
        case 'ArrowDown':
          e.preventDefault()
          onNext()
          break
        case 'ArrowLeft':
        case 'ArrowUp':
          e.preventDefault()
          onPrev()
          break
        case 'f':
        case 'F':
          onFullscreen()
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onNext, onPrev, onFullscreen])
}

// ── useProgressSave ───────────────────────────────────────────────────

export function useProgressSave(galleryId: number, currentPage: number) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      api.library.saveProgress(galleryId, currentPage).catch(() => {
        /* silent */
      })
    }, 2000) // debounce 2 s

    return () => clearTimeout(timerRef.current)
  }, [galleryId, currentPage])
}

// ── useFullscreen ─────────────────────────────────────────────────────

export function useFullscreen(containerRef: React.RefObject<HTMLElement | null>) {
  const [isFullscreen, setIsFullscreen] = useState(false)

  const toggle = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen().catch(() => {
        // iOS Safari fallback: track state manually, CSS handles the layout
        setIsFullscreen(true)
      })
    } else {
      document.exitFullscreen().catch(() => setIsFullscreen(false))
    }
  }, [containerRef])

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  return { isFullscreen, toggle }
}
