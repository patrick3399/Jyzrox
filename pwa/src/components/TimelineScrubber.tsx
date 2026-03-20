'use client'

import { useRef, useState, useCallback, useEffect, useMemo } from 'react'
import { t, getLocale } from '@/lib/i18n'

interface TimelineImage {
  added_at: string | null
}

interface TimelineScrubberProps {
  minAt: Date | null
  maxAt: Date | null
  enabled: boolean
  onJump: (timestamp: string) => void
  images?: TimelineImage[]
  scrollElement?: HTMLElement | null
  /** Timestamps evenly distributed by image count (newest first, index 0 = newest). */
  percentiles?: string[]
}

function formatDate(date: Date): string {
  return new Intl.DateTimeFormat(getLocale(), { year: 'numeric', month: 'short' }).format(date)
}

function interpolateDate(minAt: Date, maxAt: Date, ratio: number): Date {
  const minMs = minAt.getTime()
  const maxMs = maxAt.getTime()
  // ratio 0 = newest (maxAt), ratio 1 = oldest (minAt)
  return new Date(maxMs - ratio * (maxMs - minMs))
}

/**
 * Map a scrubber ratio (0 = newest, 1 = oldest) to a timestamp string.
 * Uses percentile array when available; falls back to linear interpolation.
 */
function percentileToTimestamp(percentiles: string[], ratio: number): string {
  if (percentiles.length === 0) return ''
  const idx = Math.min(percentiles.length - 1, Math.round(ratio * (percentiles.length - 1)))
  return percentiles[idx]
}

/**
 * Map an image timestamp to a scrubber ratio using the percentile array.
 * Performs a binary search for the closest percentile (percentiles[0] = newest).
 */
function timestampToPercentileRatio(timestamp: string, percentiles: string[]): number {
  if (percentiles.length <= 1) return 0
  const ts = new Date(timestamp).getTime()

  // percentiles are newest-first (descending by time), so we look for the
  // first entry whose time is <= ts, i.e. the entry that is at-or-older than ts.
  let lo = 0
  let hi = percentiles.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (new Date(percentiles[mid]).getTime() >= ts) {
      lo = mid + 1
    } else {
      hi = mid
    }
  }
  return lo / (percentiles.length - 1)
}

/** Map an image's added_at to a 0–1 ratio within the full timeline (linear fallback). */
function timestampToLinearRatio(timestamp: string, minAt: Date, maxAt: Date): number {
  const ts = new Date(timestamp).getTime()
  const minMs = minAt.getTime()
  const maxMs = maxAt.getTime()
  if (maxMs === minMs) return 0
  // 0 = newest (maxAt), 1 = oldest (minAt)
  return Math.min(1, Math.max(0, (maxMs - ts) / (maxMs - minMs)))
}

export function TimelineScrubber({
  minAt,
  maxAt,
  enabled,
  onJump,
  images,
  scrollElement,
  percentiles: percentilesProp,
}: TimelineScrubberProps) {
  // Stabilize the percentiles reference: when the prop is omitted (undefined), a default
  // parameter `percentiles = []` would create a new array on every render, causing fireJump
  // and handleDragEnd to be recreated on each render, which re-attaches drag listeners on
  // every mousemove (event listener leak). useMemo keeps the same [] identity as long as
  // the prop identity does not change.
  const percentiles = useMemo(() => percentilesProp ?? [], [percentilesProp])
  const trackRef = useRef<HTMLDivElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [thumbRatio, setThumbRatio] = useState(0) // 0 = top (newest), 1 = bottom (oldest)
  const thumbRatioRef = useRef(0)
  const [showThumb, setShowThumb] = useState(false)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Don't render if no valid range
  const hasRange = minAt && maxAt && minAt.getTime() !== maxAt.getTime()

  // Track scroll position → estimate timeline position from loaded images
  useEffect(() => {
    if (!hasRange || isDragging) return

    const handleScroll = () => {
      const maxScroll = scrollElement
        ? scrollElement.scrollHeight - scrollElement.clientHeight
        : document.documentElement.scrollHeight - window.innerHeight
      if (maxScroll <= 0) return

      const currentScroll = scrollElement ? scrollElement.scrollTop : window.scrollY
      const scrollRatio = Math.min(1, Math.max(0, currentScroll / maxScroll))

      // Map scroll position → image index → image timestamp → timeline ratio
      if (images && images.length > 0 && minAt && maxAt) {
        const idx = Math.min(images.length - 1, Math.round(scrollRatio * (images.length - 1)))
        const img = images[idx]
        if (img.added_at) {
          const ratio =
            percentiles.length > 1
              ? timestampToPercentileRatio(img.added_at, percentiles)
              : timestampToLinearRatio(img.added_at, minAt, maxAt)
          setThumbRatio(ratio)
        }
      }

      // Show thumb briefly on scroll
      setShowThumb(true)
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = setTimeout(() => setShowThumb(false), 1500)
    }

    const target = scrollElement ?? window
    target.addEventListener('scroll', handleScroll, { passive: true })
    return () => {
      target.removeEventListener('scroll', handleScroll)
      clearTimeout(hideTimerRef.current)
    }
  }, [hasRange, isDragging, images, minAt, maxAt, scrollElement, percentiles])

  const getRatioFromY = useCallback((clientY: number) => {
    const track = trackRef.current
    if (!track) return 0
    const rect = track.getBoundingClientRect()
    return Math.min(1, Math.max(0, (clientY - rect.top) / rect.height))
  }, [])

  const handleDragMove = useCallback(
    (clientY: number) => {
      if (!minAt || !maxAt) return
      const ratio = getRatioFromY(clientY)
      setThumbRatio(ratio)
      thumbRatioRef.current = ratio
    },
    [minAt, maxAt, getRatioFromY],
  )

  const fireJump = useCallback(
    (ratio: number) => {
      if (!minAt || !maxAt) return
      let timestamp: string
      if (percentiles.length > 1) {
        timestamp = percentileToTimestamp(percentiles, ratio)
      } else {
        timestamp = interpolateDate(minAt, maxAt, ratio).toISOString()
      }
      onJump(timestamp)
    },
    [minAt, maxAt, percentiles, onJump],
  )

  const handleDragEnd = useCallback(() => {
    setIsDragging(false)
    fireJump(thumbRatioRef.current)

    // Auto-hide thumb after drag
    hideTimerRef.current = setTimeout(() => setShowThumb(false), 1500)
  }, [fireJump])

  // Mouse events
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setIsDragging(true)
      setShowThumb(true)
      clearTimeout(hideTimerRef.current)
      handleDragMove(e.clientY)
    },
    [handleDragMove],
  )

  // Touch events
  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      setIsDragging(true)
      setShowThumb(true)
      clearTimeout(hideTimerRef.current)
      const touch = e.touches[0]
      if (touch) handleDragMove(touch.clientY)
    },
    [handleDragMove],
  )

  // Unified mouse + touch drag listeners
  useEffect(() => {
    if (!isDragging) return

    const onMouseMove = (e: MouseEvent) => handleDragMove(e.clientY)
    const onTouchMove = (e: TouchEvent) => {
      const touch = e.touches[0]
      if (touch) handleDragMove(touch.clientY)
    }
    const onEnd = () => handleDragEnd()

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onEnd)
    window.addEventListener('touchmove', onTouchMove, { passive: true })
    window.addEventListener('touchend', onEnd)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onEnd)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('touchend', onEnd)
    }
  }, [isDragging, handleDragMove, handleDragEnd])

  if (!hasRange || !enabled) return null

  const thumbVisible = showThumb || isDragging

  // Derive label timestamp during drag
  let labelDate: Date | null = null
  if (isDragging && minAt && maxAt) {
    if (percentiles.length > 1) {
      const ts = percentileToTimestamp(percentiles, thumbRatio)
      labelDate = ts ? new Date(ts) : null
    } else {
      labelDate = interpolateDate(minAt, maxAt, thumbRatio)
    }
  }

  return (
    <div className="timeline-scrubber" aria-label={t('images.scrubberLabel')}>
      {/* Track — always visible */}
      <div
        ref={trackRef}
        className="timeline-scrubber__track"
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
      >
        {/* Thumb + label wrapper */}
        <div
          className={`timeline-scrubber__indicator ${thumbVisible ? 'timeline-scrubber__indicator--visible' : ''}`}
          style={{ top: `${thumbRatio * 100}%` }}
        >
          {labelDate && <div className="timeline-scrubber__label">{formatDate(labelDate)}</div>}
          <div className="timeline-scrubber__thumb" />
        </div>
      </div>
    </div>
  )
}
