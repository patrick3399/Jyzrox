'use client'

import { useRef, useEffect, useCallback, useState } from 'react'

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

  const restoredRef = useRef(false)

  useEffect(() => {
    if (!isReady || restoredRef.current) return
    restoredRef.current = true
    const raw = sessionStorage.getItem(key)
    if (!raw) return
    if (!persist) sessionStorage.removeItem(key)
    try {
      const parsed = JSON.parse(raw)
      const scrollY =
        parsed !== null && typeof parsed === 'object' && 'scrollY' in parsed
          ? Number((parsed as { scrollY: unknown }).scrollY)
          : Number(raw)
      requestAnimationFrame(() => window.scrollTo(0, scrollY))
    } catch {
      requestAnimationFrame(() => window.scrollTo(0, Number(raw)))
    }
  }, [isReady, key, persist])

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
