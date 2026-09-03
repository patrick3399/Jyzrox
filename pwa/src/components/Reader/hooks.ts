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

function loadDirection(source: string, sourceId: string): ReadingDirection | null {
  if (typeof window === 'undefined') return null
  const val = localStorage.getItem(`reader_direction_${source}_${sourceId}`)
  if (val === 'ltr' || val === 'rtl' || val === 'vertical') return val
  return null
}

function saveDirection(source: string, sourceId: string, dir: ReadingDirection) {
  if (typeof window === 'undefined') return
  localStorage.setItem(`reader_direction_${source}_${sourceId}`, dir)
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

export function useReaderState(
  initialPage: number,
  totalPages: number,
  source: string,
  sourceId: string,
) {
  const settings = loadReaderSettings()
  const savedDirection = loadDirection(source, sourceId)

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
      saveDirection(source, sourceId, direction)
    },
    [source, sourceId],
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
const PROXY_PREFETCH_CONCURRENCY = 4
/** Timeout (ms) per image in proxy mode before giving up and moving on */
const PROXY_PREFETCH_TIMEOUT_MS = 10000
/**
 * How many pages ahead of the current page a page-turn cleanup keeps alive.
 * Page turns abort only requests outside [currentPage, currentPage + this],
 * so a fast flip can keep building a buffer instead of restarting the chain
 * every turn. The upper bound is what stops this from regressing FE-T16's
 * memory incident on a long fast flip.
 */
const PREFETCH_KEEP_AHEAD = 10

/** Bookkeeping for one in-flight/active prefetch <img> element. */
interface ActiveImage {
  el: HTMLImageElement
  /** Proxy-mode per-image timeout; null in local mode (no timeout there). */
  timeoutId: ReturnType<typeof setTimeout> | null
  /** Whether this request incremented inflightCountRef (proxy mode only). */
  counted: boolean
}

export function useSequentialPrefetch(
  images: ReaderImage[],
  currentPage: number,
  isProxyMode: boolean,
): Set<number> {
  const [prefetched, setPrefetched] = useState<Set<number>>(new Set())
  // Number of requests currently in flight (proxy mode)
  const inflightCountRef = useRef(0)
  const prefetchedRef = useRef<Set<number>>(new Set())
  // Pages with a request currently in flight. Without this, a re-render that
  // restarts the chain issues a second request for a page whose first request
  // has not settled yet — for a large file that means downloading it twice.
  const inflightPagesRef = useRef<Set<number>>(new Set())
  // Active Image elements keyed by page, for cleanup on unmount / page change.
  // Keyed by page (rather than a bare Set) so a page-turn cleanup can abort
  // only the pages that fell outside the keep-ahead window.
  const activeImagesRef = useRef<Map<number, ActiveImage>>(new Map())
  const unmountedRef = useRef(false)

  // Reader rebuilds its `images` array on every render, so reading it through a
  // ref keeps prefetchPage — and therefore the effect below — stable. Keying
  // the effect on the array identity made every Reader render abort and re-issue
  // the whole prefetch window, including the renders this hook triggers itself
  // when a prefetch settles.
  const imagesRef = useRef(images)
  useEffect(() => {
    imagesRef.current = images
  }, [images])

  // Changes only when the set of prefetchable pages actually changes (pages
  // appended by infinite scroll, a still-downloading page gaining a URL, a page
  // hidden) — not when the array is merely rebuilt with identical content.
  const prefetchableKey = images
    .map((img) => (img.mediaType === 'video' ? 'v' : img.url ? '1' : '0'))
    .join('')

  // prefetchPage needs a stable reference so we use useRef to break the
  // circular dependency with the chain callback.
  const prefetchPageRef = useRef<(pageNum: number) => void>(() => undefined)

  // Epoch: incremented on every currentPage change.
  // Each in-flight callback captures its epoch; if it doesn't match the
  // current epoch by the time it fires, it was started for a stale page
  // position and must not keep marching forward from that stale position —
  // see currentPageRef below for where it re-enters instead.
  const epochRef = useRef(0)

  // Latest currentPage, readable from within prefetchPage's closures (which
  // are recreated far less often than currentPage changes). Declared here —
  // before prefetchPage — so it's initialised by the time those closures
  // capture it. A settling request whose epoch has gone stale uses this to
  // re-enter the chain at the current frontier instead of abandoning it;
  // otherwise the chain goes idle between page turns (see hop-forward loop
  // in prefetchPage, which skips anything already prefetched/in-flight, so
  // re-entering here never re-requests a page that's already covered).
  const currentPageRef = useRef(currentPage)
  useEffect(() => {
    currentPageRef.current = currentPage
  }, [currentPage])

  // Cleanup helper: detach handlers, stop loading, clear any pending timeout,
  // and drop the page's bookkeeping entry.
  const cleanupImage = useCallback((pageNum: number) => {
    const entry = activeImagesRef.current.get(pageNum)
    if (!entry) return
    if (entry.timeoutId !== null) clearTimeout(entry.timeoutId)
    entry.el.onload = null
    entry.el.onerror = null
    entry.el.src = ''
    activeImagesRef.current.delete(pageNum)
  }, [])

  // Cleanup all active images (used on unmount only — page turns use the
  // windowed cleanup below so useful in-flight prefetches survive).
  const cleanupAllImages = useCallback(() => {
    Array.from(activeImagesRef.current.keys()).forEach((pageNum) => cleanupImage(pageNum))
    activeImagesRef.current.clear()
    inflightPagesRef.current.clear()
  }, [cleanupImage])

  // Abort only the in-flight/active prefetches whose page falls outside
  // [minPage, maxPage], decrementing the inflight counter for the ones that
  // contributed to it. Pages inside the window are left running so a page
  // turn doesn't throw away a buffer that's already being built.
  const cleanupImagesOutsideWindow = useCallback(
    (minPage: number, maxPage: number) => {
      activeImagesRef.current.forEach((entry, pageNum) => {
        if (pageNum >= minPage && pageNum <= maxPage) return
        cleanupImage(pageNum)
        inflightPagesRef.current.delete(pageNum)
        if (entry.counted) {
          inflightCountRef.current = Math.max(0, inflightCountRef.current - 1)
        }
      })
    },
    [cleanupImage],
  )

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      unmountedRef.current = true
      cleanupAllImages()
    }
  }, [cleanupAllImages])

  // A page is worth starting a request for when nothing is already covering it
  // and it is not a video. Videos must never be routed through an <img>: the
  // decoder can never use the bytes, but the browser downloads the entire file
  // before it gives up and fires onerror, so prefetching a large video costs
  // its full size in memory for nothing. Videos load from their <video> element.
  const canPrefetch = useCallback(
    (img: ReaderImage) =>
      img.mediaType !== 'video' &&
      !prefetchedRef.current.has(img.pageNum) &&
      !inflightPagesRef.current.has(img.pageNum),
    [],
  )

  const prefetchPage = useCallback(
    (requestedPage: number) => {
      const images = imagesRef.current
      let idx = images.findIndex((i) => i.pageNum === requestedPage)
      if (idx < 0) return

      if (isProxyMode) {
        // Chain semantics: hop forward over pages that cannot be started right
        // now instead of stalling the slot on them.
        while (idx < images.length && !canPrefetch(images[idx])) idx += 1
        if (idx >= images.length) return
      }

      const img = images[idx]
      if (!canPrefetch(img)) return
      const pageNum = img.pageNum

      if (isProxyMode) {
        // Proxy mode: allow up to PROXY_PREFETCH_CONCURRENCY concurrent requests.
        // Each request has a timeout; on timeout it is treated as done and the
        // chain continues to the next page so a slow image never blocks the queue.
        if (inflightCountRef.current >= PROXY_PREFETCH_CONCURRENCY) return
        if (!img.url) return // skip un-downloaded images — no proxy available

        inflightCountRef.current += 1
        inflightPagesRef.current.add(pageNum)
        const capturedEpoch = epochRef.current

        const el = new window.Image()
        const entry: ActiveImage = { el, timeoutId: null, counted: true }
        activeImagesRef.current.set(pageNum, entry)

        // Timeout: if image hasn't loaded within threshold, skip and continue chain.
        // The count is decremented unconditionally — it was incremented
        // unconditionally above, and a stale epoch only means "don't keep
        // marching forward from the stale page position", not "this slot was
        // never actually used" or "stop prefetching altogether" (see the
        // re-entry logic below).
        const timeoutId = setTimeout(() => {
          cleanupImage(pageNum)
          inflightPagesRef.current.delete(pageNum)
          inflightCountRef.current = Math.max(0, inflightCountRef.current - 1)
          if (unmountedRef.current) return
          // Skip this page (don't add to prefetched) and try next. If the
          // epoch is still current, continue from this page in sequence; if
          // a page turn moved on since this request started, don't keep
          // marching forward from the abandoned position — re-enter the
          // chain at the current frontier instead so prefetching doesn't go
          // idle until the next page turn.
          const nextPage = capturedEpoch === epochRef.current ? pageNum + 1 : currentPageRef.current + 1
          prefetchPageRef.current(nextPage)
        }, PROXY_PREFETCH_TIMEOUT_MS)
        entry.timeoutId = timeoutId

        el.onload = el.onerror = () => {
          clearTimeout(timeoutId)
          cleanupImage(pageNum)
          inflightPagesRef.current.delete(pageNum)
          inflightCountRef.current = Math.max(0, inflightCountRef.current - 1)

          if (unmountedRef.current) return

          // Record the page as prefetched even if a page turn moved the epoch
          // on since this request started — the bytes are in the browser
          // cache either way, so dropping the bookkeeping would only cause a
          // pointless re-request later.
          prefetchedRef.current = new Set([...prefetchedRef.current, pageNum])
          setPrefetched(new Set(prefetchedRef.current))

          // If the epoch is still current, continue this chain from the next
          // page in sequence. If a page turn moved the epoch on since this
          // request started, don't keep marching forward from a page
          // position the user has left — re-enter the chain at the current
          // frontier instead. prefetchPage's hop-forward loop skips anything
          // already prefetched/in-flight, so this lands on the first
          // genuinely useful page rather than re-requesting anything, and
          // keeps the buffer advancing between page turns instead of going
          // idle once every in-flight request from the old epoch settles.
          const nextPage = capturedEpoch === epochRef.current ? pageNum + 1 : currentPageRef.current + 1
          prefetchPageRef.current(nextPage)
        }
        el.src = img.url
      } else {
        // Local mode: fire-and-forget (concurrent, up to 3 ahead from caller)
        if (!img.url) return // skip un-downloaded images
        inflightPagesRef.current.add(pageNum)
        const el = new window.Image()
        activeImagesRef.current.set(pageNum, { el, timeoutId: null, counted: false })
        el.onload = el.onerror = () => {
          cleanupImage(pageNum)
          inflightPagesRef.current.delete(pageNum)
          if (unmountedRef.current) return

          prefetchedRef.current = new Set([...prefetchedRef.current, pageNum])
          setPrefetched(new Set(prefetchedRef.current))
        }
        el.src = img.url
      }
    },
    [isProxyMode, cleanupImage, canPrefetch],
  )

  // Keep the ref in sync with the latest callback
  useEffect(() => {
    prefetchPageRef.current = prefetchPage
  }, [prefetchPage])

  const startPrefetchWindow = useCallback(
    (page: number) => {
      if (isProxyMode) {
        // Start parallel prefetch chains — fire PROXY_PREFETCH_CONCURRENCY starting
        // pages so we have multiple requests in flight without strict serialisation.
        for (let slot = 0; slot < PROXY_PREFETCH_CONCURRENCY; slot++) {
          prefetchPage(page + 1 + slot)
        }
      } else {
        // Local: prefetch forward 5 + backward 2 concurrently
        for (let i = 1; i <= 5; i++) {
          prefetchPage(page + i)
        }
        for (let i = 1; i <= 2; i++) {
          prefetchPage(page - i)
        }
      }
    },
    [isProxyMode, prefetchPage],
  )

  useEffect(() => {
    // Advance epoch so any stale in-flight callback from the previous page
    // will, once it settles, re-enter its chain at the current frontier
    // (currentPageRef.current + 1) instead of continuing to march forward
    // from the page position the user has left. Bookkeeping — recording the
    // page as prefetched and decrementing the inflight count — always
    // happens regardless of epoch; see the onload/onerror/timeout handlers.
    epochRef.current += 1

    // Abort only the prefetches that fell outside the keep-ahead window.
    // Do NOT reset inflightCountRef here: it is now decremented accurately as
    // each request settles or is aborted below, so PROXY_PREFETCH_CONCURRENCY
    // stays a real cap instead of being reset on every page turn — which is
    // what let fast flipping cancel a buffer that was still being built.
    cleanupImagesOutsideWindow(currentPage, currentPage + PREFETCH_KEEP_AHEAD)

    startPrefetchWindow(currentPage)
  }, [currentPage, startPrefetchWindow, cleanupImagesOutsideWindow])

  // Pages that only became prefetchable later (appended by infinite scroll, or
  // finished downloading and gained a URL) still need a request. Top the window
  // up without tearing down the requests already running for this page — that
  // teardown-and-restart is what turned one page turn into repeated downloads
  // of the same file. (currentPageRef itself is declared above, before
  // prefetchPage, so its stale-epoch re-entry logic can read it too.)
  useEffect(() => {
    startPrefetchWindow(currentPageRef.current)
  }, [prefetchableKey, startPrefetchWindow])

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

// ── useProgressSave ───────────────────────────────────────────────────

export function useProgressSave(
  source: string,
  sourceId: string,
  currentPage: number,
  enabled = true,
) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const retryRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const currentPageRef = useRef(currentPage)

  useEffect(() => {
    currentPageRef.current = currentPage
  }, [currentPage])

  useEffect(() => {
    if (!source || !sourceId || !enabled) return

    const flushProgress = () => {
      clearTimeout(timerRef.current)
      clearTimeout(retryRef.current)
      void api.library
        .saveProgress(source, sourceId, currentPageRef.current, { keepalive: true })
        .catch((err) => {
          // Browsers may still reject background requests while suspending a PWA.
          // The next foreground page change will retry through the normal path.
          console.warn('[Reader] Failed to flush progress while leaving the page:', err)
        })
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') flushProgress()
    }

    window.addEventListener('pagehide', flushProgress)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('pagehide', flushProgress)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [source, sourceId, enabled])

  useEffect(() => {
    // Skip progress save for proxy-only browsing or when disabled
    if (!source || !sourceId || !enabled) return

    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      api.library.saveProgress(source, sourceId, currentPage).catch((err) => {
        console.warn('[Reader] Failed to save progress, retrying in 5s:', err)
        clearTimeout(retryRef.current)
        retryRef.current = setTimeout(() => {
          api.library.saveProgress(source, sourceId, currentPage).catch((retryErr) => {
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
  }, [source, sourceId, currentPage, enabled])
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
