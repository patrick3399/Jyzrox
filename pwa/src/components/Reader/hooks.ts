'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReaderImage } from './types'
import { neighbouringPages, sortPageNums } from './pageOrder'
import {
  MAX_PROXY_CONCURRENCY,
  nextProxyConcurrency,
  planProxyPrefetch,
  recordTurn,
  type PageTurn,
} from './proxyPrefetchPolicy'

export { loadReaderSettings, saveReaderSettings } from './readerSettings'
export { useReaderState } from './useReaderState'
export { useTouchGesture, useKeyboardNav } from './useReaderInput'
export { useProgressSave, useAutoAdvance, useStatusBarClock } from './useReaderTimers'
export { usePinchZoom } from './usePinchZoom'
export { useViewportHeight } from './useViewportHeight'

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
