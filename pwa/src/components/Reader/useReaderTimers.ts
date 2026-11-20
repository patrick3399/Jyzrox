'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'

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
