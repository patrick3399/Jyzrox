'use client'

import { useRef, useEffect, useCallback, useState } from 'react'

type ScrollPositionRestoreOptions = {
  scrollY: number | null
  isReady: boolean
  restoreKey: string
  onRestored?: () => void
}

/**
 * Apply one scroll position per logical view identity once its content is ready.
 *
 * Callers keep ownership of their cached view data. This hook only owns the
 * restore lifecycle, allowing pages with richer snapshot formats to share the
 * same scroll application path as the simple sessionStorage helper below.
 */
export function useScrollPositionRestore({
  scrollY,
  isReady,
  restoreKey,
  onRestored,
}: ScrollPositionRestoreOptions) {
  const restoredKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (!isReady || scrollY === null || !Number.isFinite(scrollY)) return
    if (restoredKeyRef.current === restoreKey) return
    restoredKeyRef.current = restoreKey
    onRestored?.()
    requestAnimationFrame(() => window.scrollTo(0, scrollY))
  }, [isReady, onRestored, restoreKey, scrollY])
}

function readStoredScrollY(key: string): number | null {
  if (typeof window === 'undefined') return null
  const raw = sessionStorage.getItem(key)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    return parsed !== null && typeof parsed === 'object' && 'scrollY' in parsed
      ? Number((parsed as { scrollY: unknown }).scrollY)
      : Number(raw)
  } catch {
    return Number(raw)
  }
}

export function useScrollRestore<T = unknown>(
  key: string,
  isReady: boolean,
  options?: { persist?: boolean },
) {
  // persist mode: restore is non-consuming and scroll position is captured
  // continuously, so leaving via a bottom-tab switch (which never calls
  // saveScroll) still records the position and round-tripping keeps working.
  const persist = options?.persist ?? false
  // Read pages synchronously (useState initializer) so they are available on the very first render
  // as useSWRInfinite fallbackData — intentionally eager regardless of isReady (callers may use it
  // immediately as fallbackData). key must be stable per instance; changing it after mount leaves
  // restoredPages stale (useState initializer only runs once).
  const [restoredPages] = useState<T[] | null>(() => {
    if (typeof window === 'undefined') return null
    try {
      const raw = sessionStorage.getItem(key)
      if (!raw) return null
      const parsed = JSON.parse(raw)
      if (
        parsed !== null &&
        typeof parsed === 'object' &&
        Array.isArray((parsed as { pages?: unknown }).pages)
      ) {
        const pages = (parsed as { pages: T[] }).pages
        return pages.length > 0 ? pages : null
      }
    } catch {
      // legacy string format — no pages
    }
    return null
  })

  const storedScrollY = readStoredScrollY(key)
  const consumeRestore = useCallback(() => {
    if (!persist) sessionStorage.removeItem(key)
  }, [key, persist])
  useScrollPositionRestore({
    scrollY: storedScrollY,
    isReady,
    restoreKey: key,
    onRestored: consumeRestore,
  })

  // Continuous scroll capture (persist + ready only). Gated on isReady so that
  // inactive instances (e.g. non-active pixiv sub-tabs) don't overwrite their
  // own key with the active tab's scrollY.
  useEffect(() => {
    if (!persist || !isReady) return
    let raf = 0
    const onScroll = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        let pages: T[] | undefined
        const raw = sessionStorage.getItem(key)
        if (raw) {
          try {
            const parsed = JSON.parse(raw)
            if (parsed !== null && typeof parsed === 'object' && Array.isArray(parsed.pages)) {
              pages = parsed.pages as T[]
            }
          } catch {
            // legacy string format — no pages to preserve
          }
        }
        sessionStorage.setItem(
          key,
          JSON.stringify(
            pages !== undefined
              ? { scrollY: window.scrollY, pages }
              : { scrollY: window.scrollY },
          ),
        )
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [persist, isReady, key])

  const saveScroll = useCallback(
    (pages?: T[]) => {
      if (typeof window === 'undefined') return
      if (pages !== undefined) {
        sessionStorage.setItem(key, JSON.stringify({ scrollY: window.scrollY, pages }))
      } else {
        sessionStorage.setItem(key, String(window.scrollY))
      }
    },
    [key],
  )

  return { saveScroll, restoredPages }
}
