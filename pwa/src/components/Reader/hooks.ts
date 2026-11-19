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
import { nearestPage, neighbouringPages, sortPageNums, stepPage } from './pageOrder'
import {
  MAX_PROXY_CONCURRENCY,
  nextProxyConcurrency,
  planProxyPrefetch,
  recordTurn,
  type PageTurn,
} from './proxyPrefetchPolicy'
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
    case 'SHOW_GRID':
      return { ...state, isGridOpen: true }
    case 'HIDE_GRID':
      return { ...state, isGridOpen: false }
    default:
      return state
  }
}

export function useReaderState(
  initialPage: number,
  totalPages: number,
  source: string,
  sourceId: string,
  /**
   * The pages that exist, sorted, once the set is final: navigation then walks
   * this list. Null while pages may still arrive (download in flight, EH proxy),
   * where a number missing from the list can be a page worth waiting on.
   */
  settledPages: readonly number[] | null = null,
) {
  const settings = loadReaderSettings()
  const savedDirection = loadDirection(source, sourceId)

  const [state, dispatch] = useReducer(readerReducer, {
    currentPage: settledPages ? nearestPage(settledPages, initialPage) : initialPage,
    viewMode: settings.defaultViewMode,
    showOverlay: false,
    scaleMode: settings.defaultScaleMode,
    readingDirection: savedDirection ?? settings.defaultReadingDirection,
    isGridOpen: false,
  } as ReaderState)

  const setPage = useCallback(
    (page: number) => {
      const target = settledPages
        ? nearestPage(settledPages, page)
        : Math.max(1, Math.min(totalPages, page))
      dispatch({ type: 'SET_PAGE', page: target })
    },
    [settledPages, totalPages],
  )

  const nextPage = useCallback(
    () =>
      setPage(settledPages ? stepPage(settledPages, state.currentPage, 1) : state.currentPage + 1),
    [settledPages, state.currentPage, setPage],
  )

  const prevPage = useCallback(
    () =>
      setPage(settledPages ? stepPage(settledPages, state.currentPage, -1) : state.currentPage - 1),
    [settledPages, state.currentPage, setPage],
  )

  // The current page can stop existing: a refresh after its file was deleted,
  // or a download settling with this page among the ones that failed.
  useEffect(() => {
    if (!settledPages) return
    const page = nearestPage(settledPages, state.currentPage)
    if (page !== state.currentPage) dispatch({ type: 'SET_PAGE', page })
  }, [settledPages, state.currentPage])

  const setViewMode = useCallback((mode: ViewMode) => dispatch({ type: 'SET_VIEW_MODE', mode }), [])

  const toggleOverlay = useCallback(() => dispatch({ type: 'TOGGLE_OVERLAY' }), [])

  const showGrid = useCallback(() => dispatch({ type: 'SHOW_GRID' }), [])

  const hideGrid = useCallback(() => dispatch({ type: 'HIDE_GRID' }), [])

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
    showGrid,
    hideGrid,
  }
}

// ── useSequentialPrefetch ─────────────────────────────────────────────
// Core feature: prefetch control with parallel slots + per-image timeout

/** Timeout (ms) per image in proxy mode before giving up on that page */
const PROXY_PREFETCH_TIMEOUT_MS = 10000
/**
 * How long proxy prefetch waits for the current page to report ready before
 * starting anyway. A video page, or an image still in ReaderImg's retry
 * backoff, may never report it.
 */
export const PROXY_CURRENT_PAGE_GRACE_MS = 2500
/**
 * How many pages ahead of the current page a page-turn cleanup keeps alive.
 * Page turns abort only requests outside [currentPage, currentPage + this],
 * so a fast flip can keep building a buffer instead of restarting the window
 * every turn. The upper bound is what stops this from regressing FE-T16's
 * memory incident on a long fast flip.
 */
const PREFETCH_KEEP_AHEAD = 10
/** Max concurrent in-flight prefetch requests in local mode */
const LOCAL_PREFETCH_CONCURRENCY = 2
/** Local mode prefetch window: pages ahead / behind the current page */
const LOCAL_PREFETCH_AHEAD = 5
const LOCAL_PREFETCH_BEHIND = 2
/**
 * Decoded-pixel budget for one local prefetch window. Local pages are original
 * files, so a gallery of 5336x8000 (~40 MB) JPEGs fetched 7 at a time starved
 * iOS Safari's network and memory until the app stopped responding even after
 * leaving the Reader. Ordinary ~6 MP pages still get the full window; huge
 * originals shrink it to the next page only.
 */
const LOCAL_PREFETCH_PIXEL_BUDGET = 48_000_000
/** Pixel estimate for a page whose dimensions are unknown */
const LOCAL_PREFETCH_UNKNOWN_PIXELS = 6_000_000
/** Weight of the newest sample in the smoothed proxy fetch latency */
const LATENCY_SMOOTHING = 0.3

/** Bookkeeping for one in-flight/active prefetch <img> element. */
interface ActiveImage {
  el: HTMLImageElement
  /** Proxy-mode per-image timeout; null in local mode (no timeout there). */
  timeoutId: ReturnType<typeof setTimeout> | null
  /** Whether this request incremented inflightCountRef. */
  counted: boolean
}

export interface SequentialPrefetchOptions {
  /**
   * Proxy mode: false while the current page is still loading. Prefetch waits
   * for it (at most PROXY_CURRENT_PAGE_GRACE_MS) so neighbours do not compete
   * with the page on screen for the server's EH request slots.
   */
  currentPageReady?: boolean
}

/**
 * Prefetch the pages around the current one into the browser HTTP cache.
 *
 * Local mode keeps a fixed window (LOCAL_PREFETCH_AHEAD / BEHIND, shrunk by a
 * decoded-pixel budget). Proxy mode sizes its window from how the reader moves
 * (`proxyPrefetchPolicy.ts`), because every proxied page costs EH requests and
 * quota: it used to chain pageNum + 1 with no forward limit, so a reader
 * resting on one page pulled the whole gallery from EH.
 */
export function useSequentialPrefetch(
  images: ReaderImage[],
  currentPage: number,
  isProxyMode: boolean,
  options: SequentialPrefetchOptions = {},
): Set<number> {
  const currentPageReady = options.currentPageReady ?? true
  const [prefetched, setPrefetched] = useState<Set<number>>(new Set())
  // Number of requests currently in flight
  const inflightCountRef = useRef(0)
  const prefetchedRef = useRef<Set<number>>(new Set())
  // Pages with a request currently in flight. Without this, a re-render that
  // restarts the window issues a second request for a page whose first request
  // has not settled yet — for a large file that means downloading it twice.
  const inflightPagesRef = useRef<Set<number>>(new Set())
  // Active Image elements keyed by page, for cleanup on unmount / page change.
  // Keyed by page (rather than a bare Set) so a page-turn cleanup can abort
  // only the pages that fell outside the keep window.
  const activeImagesRef = useRef<Map<number, ActiveImage>>(new Map())
  const unmountedRef = useRef(false)

  // Proxy-mode navigation state (see proxyPrefetchPolicy.ts).
  const turnsRef = useRef<PageTurn[]>([])
  const previousPageRef = useRef<number | null>(null)
  const latencyRef = useRef<number | null>(null)
  const concurrencyRef = useRef(MAX_PROXY_CONCURRENCY)
  // Pages whose prefetch timed out; not retried until the next page turn.
  const timedOutRef = useRef<Set<number>>(new Set())
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const currentPageReadyRef = useRef(currentPageReady)
  // The page whose readiness wait ran out (PROXY_CURRENT_PAGE_GRACE_MS).
  const graceReleasedPageRef = useRef<number | null>(null)

  // Reader rebuilds its `images` array on every render, so reading it through a
  // ref keeps the request callbacks — and therefore the effects below — stable.
  // Keying the effect on the array identity made every Reader render abort and
  // re-issue the whole prefetch window, including the renders this hook
  // triggers itself when a prefetch settles.
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

  // Settle callbacks are created inside the request functions — before
  // startPrefetchWindow exists — and top the window up through this ref.
  const startPrefetchWindowRef = useRef<(page: number) => void>(() => undefined)

  // Latest currentPage, readable from settle callbacks, which outlive the
  // render they were created in.
  const currentPageRef = useRef(currentPage)
  useEffect(() => {
    currentPageRef.current = currentPage
  }, [currentPage])

  // Before the page-turn effect below, so a turn that lands on a page that has
  // not loaded yet sees `false` in the same commit.
  useEffect(() => {
    currentPageReadyRef.current = currentPageReady
    if (currentPageReady) startPrefetchWindowRef.current(currentPageRef.current)
  }, [currentPageReady])

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
      if (holdTimerRef.current) clearTimeout(holdTimerRef.current)
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
      !inflightPagesRef.current.has(img.pageNum) &&
      !timedOutRef.current.has(img.pageNum),
    [],
  )

  const markPrefetched = useCallback((pageNum: number) => {
    prefetchedRef.current = new Set([...prefetchedRef.current, pageNum])
    setPrefetched(new Set(prefetchedRef.current))
  }, [])

  // Proxy mode: one request with a timeout. Every outcome feeds the latency and
  // concurrency estimates, then tops the window up around wherever the reader
  // is now (which may not be where they were when the request started).
  const requestProxyPage = useCallback(
    (img: ReaderImage) => {
      if (!img.url || !canPrefetch(img)) return
      if (inflightCountRef.current >= concurrencyRef.current) return
      const pageNum = img.pageNum
      const startedAt = Date.now()

      inflightCountRef.current += 1
      inflightPagesRef.current.add(pageNum)

      const el = new window.Image()
      const entry: ActiveImage = { el, timeoutId: null, counted: true }
      activeImagesRef.current.set(pageNum, entry)

      const settle = (outcome: 'load' | 'error' | 'timeout') => {
        cleanupImage(pageNum)
        inflightPagesRef.current.delete(pageNum)
        inflightCountRef.current = Math.max(0, inflightCountRef.current - 1)
        if (unmountedRef.current) return

        const ms = Date.now() - startedAt
        concurrencyRef.current = nextProxyConcurrency(concurrencyRef.current, {
          ok: outcome === 'load',
          ms,
        })
        if (outcome === 'load') {
          latencyRef.current =
            latencyRef.current === null
              ? ms
              : latencyRef.current * (1 - LATENCY_SMOOTHING) + ms * LATENCY_SMOOTHING
        }
        if (outcome === 'timeout') {
          // Skip it for now; the next page turn may try again.
          timedOutRef.current.add(pageNum)
        } else {
          // Recorded even after a page turn: the bytes (or the failure) are in
          // the browser cache either way, and dropping the bookkeeping would
          // only cause a pointless re-request later.
          markPrefetched(pageNum)
        }
        startPrefetchWindowRef.current(currentPageRef.current)
      }

      entry.timeoutId = setTimeout(() => settle('timeout'), PROXY_PREFETCH_TIMEOUT_MS)
      el.onload = () => settle('load')
      el.onerror = () => settle('error')
      el.src = img.url
    },
    [canPrefetch, cleanupImage, markPrefetched],
  )

  // Local mode: up to LOCAL_PREFETCH_CONCURRENCY in flight; each settle tops
  // the current window up instead of firing the whole window at once.
  const requestLocalPage = useCallback(
    (img: ReaderImage) => {
      if (!img.url || !canPrefetch(img)) return
      if (inflightCountRef.current >= LOCAL_PREFETCH_CONCURRENCY) return
      const pageNum = img.pageNum
      inflightCountRef.current += 1
      inflightPagesRef.current.add(pageNum)
      const el = new window.Image()
      activeImagesRef.current.set(pageNum, { el, timeoutId: null, counted: true })
      el.onload = el.onerror = () => {
        cleanupImage(pageNum)
        inflightPagesRef.current.delete(pageNum)
        inflightCountRef.current = Math.max(0, inflightCountRef.current - 1)
        if (unmountedRef.current) return
        markPrefetched(pageNum)
        startPrefetchWindowRef.current(currentPageRef.current)
      }
      el.src = img.url
    },
    [canPrefetch, cleanupImage, markPrefetched],
  )

  const startPrefetchWindow = useCallback(
    (page: number) => {
      const byPage = new Map(imagesRef.current.map((img) => [img.pageNum, img]))
      const sorted = sortPageNums([...byPage.keys()])

      if (isProxyMode) {
        if (typeof document !== 'undefined' && document.hidden) return
        if (!currentPageReadyRef.current && graceReleasedPageRef.current !== page) return

        const plan = planProxyPrefetch(turnsRef.current, Date.now(), latencyRef.current)
        if (holdTimerRef.current) {
          clearTimeout(holdTimerRef.current)
          holdTimerRef.current = undefined
        }
        if (plan.kind === 'hold') {
          holdTimerRef.current = setTimeout(
            () => {
              holdTimerRef.current = undefined
              startPrefetchWindowRef.current(currentPageRef.current)
            },
            Math.max(0, plan.resumeAt - Date.now()),
          )
          return
        }
        const { after, before } = neighbouringPages(sorted, page, plan.ahead, plan.behind)
        // Nearest first, in the direction the reader is moving.
        const order = plan.reason === 'backward' ? [...before, ...after] : [...after, ...before]
        for (const pageNum of order) {
          if (inflightCountRef.current >= concurrencyRef.current) break
          const img = byPage.get(pageNum)
          if (img) requestProxyPage(img)
        }
        return
      }

      // Local: forward pages first, then backward, until the pixel budget is
      // spent. The next page is always kept so reading never waits on it.
      const { after, before } = neighbouringPages(
        sorted,
        page,
        LOCAL_PREFETCH_AHEAD,
        LOCAL_PREFETCH_BEHIND,
      )
      let pixels = 0
      let kept = 0
      for (const pageNum of [...after, ...before]) {
        const img = byPage.get(pageNum)
        if (!img || !img.url || img.mediaType === 'video') continue
        pixels += img.width && img.height ? img.width * img.height : LOCAL_PREFETCH_UNKNOWN_PIXELS
        if (kept > 0 && pixels > LOCAL_PREFETCH_PIXEL_BUDGET) break
        kept += 1
        requestLocalPage(img)
      }
    },
    [isProxyMode, requestProxyPage, requestLocalPage],
  )

  useEffect(() => {
    startPrefetchWindowRef.current = startPrefetchWindow
  }, [startPrefetchWindow])

  useEffect(() => {
    const previous = previousPageRef.current
    previousPageRef.current = currentPage
    let keepBehind = 0
    let keepAhead = PREFETCH_KEEP_AHEAD

    if (isProxyMode) {
      if (previous !== null && previous !== currentPage) {
        turnsRef.current = recordTurn(turnsRef.current, Date.now(), currentPage - previous)
        timedOutRef.current = new Set()
      }
      const plan = planProxyPrefetch(turnsRef.current, Date.now(), latencyRef.current)
      if (plan.kind === 'window') {
        keepBehind = plan.behind
        // Paging backwards: the pages ahead were just read; free their slots.
        if (plan.ahead === 0) keepAhead = 0
      }
    }

    // Abort only the prefetches that fell outside the keep window. Do NOT reset
    // inflightCountRef here: it is decremented accurately as each request
    // settles or is aborted, so the concurrency cap stays real instead of being
    // reset on every page turn — which is what let fast flipping cancel a
    // buffer that was still being built.
    cleanupImagesOutsideWindow(currentPage - keepBehind, currentPage + keepAhead)

    startPrefetchWindow(currentPage)
  }, [currentPage, isProxyMode, startPrefetchWindow, cleanupImagesOutsideWindow])

  // Proxy mode: a current page that never reports ready (a video, an image
  // still retrying) must not keep its neighbours unfetched for good.
  useEffect(() => {
    if (!isProxyMode || currentPageReady) return
    const page = currentPage
    const timer = setTimeout(() => {
      graceReleasedPageRef.current = page
      startPrefetchWindowRef.current(currentPageRef.current)
    }, PROXY_CURRENT_PAGE_GRACE_MS)
    return () => clearTimeout(timer)
  }, [currentPage, currentPageReady, isProxyMode])

  // Proxy mode: a backgrounded tab fetches nothing; catch up when it returns.
  useEffect(() => {
    if (!isProxyMode) return
    const onVisibilityChange = () => {
      if (!document.hidden) startPrefetchWindowRef.current(currentPageRef.current)
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [isProxyMode])

  // Pages that only became prefetchable later (appended by infinite scroll, or
  // finished downloading and gained a URL) still need a request. Top the window
  // up without tearing down the requests already running for this page — that
  // teardown-and-restart is what turned one page turn into repeated downloads
  // of the same file.
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
