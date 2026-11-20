'use client'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ReaderImage } from './types'
import { THUMB_STRIP_CELL_HEIGHT, THUMB_STRIP_PADDING_Y } from './layout'
import { ThumbnailCell } from './ThumbnailCell'

interface ThumbnailStripProps {
  images: ReaderImage[]
  currentPage: number
  onPageSelect: (page: number) => void
  /** Preview thumbs from EH CDN: { "1": "url" or "url|ox|w|h" } */
  previews?: Record<string, string>
  /** Called with the rightmost visible page when the strip is scrolled — used to load more EH previews */
  onScrollToPage?: (page: number) => void
  /** Whether the strip is currently visible. scrollIntoView is suppressed when false. */
  isVisible?: boolean
  readingDirection?: 'ltr' | 'rtl' | 'vertical'
}

export function ThumbnailStrip({
  images,
  currentPage,
  onPageSelect,
  previews,
  onScrollToPage,
  isVisible: _isVisible,
  readingDirection,
}: ThumbnailStripProps) {
  const activeRef = useRef<HTMLDivElement | null>(null)
  const stripRef = useRef<HTMLDivElement | null>(null)
  const userScrollingRef = useRef(false)
  // Cache natural sprite dimensions per URL for pixel-perfect background-size.
  const [spriteNaturalSizes, setSpriteNaturalSizes] = useState<
    Record<string, { w: number; h: number }>
  >({})
  // Virtual scroll: only render thumbnails in the visible range
  const THUMB_TOTAL_W = 64 // 60px thumb + 4px gap
  const BUFFER = 10
  const [visibleRange, setVisibleRange] = useState({ start: 0, end: 50 })

  const spriteUrls = useMemo(() => {
    if (!previews) return []
    const urls = new Set<string>()
    for (const raw of Object.values(previews)) {
      if (raw.includes('|'))
        urls.add(`/api/eh/thumb-proxy?url=${encodeURIComponent(raw.split('|')[0])}`)
    }
    return [...urls]
  }, [previews])

  const displayImages = useMemo(
    () => (readingDirection === 'rtl' ? [...images].reverse() : images),
    [images, readingDirection],
  )
  const displayImagesRef = useRef(displayImages)
  useEffect(() => {
    displayImagesRef.current = displayImages
  }, [displayImages])

  const programmaticScrollRef = useRef(false)
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const scrollNotifyThrottleRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const lastScrollNotifyPageRef = useRef(0)
  const onScrollToPageRef = useRef(onScrollToPage)
  useEffect(() => {
    onScrollToPageRef.current = onScrollToPage
  }, [onScrollToPage])

  useEffect(() => {
    const el = stripRef.current
    if (!el) return
    const onScroll = () => {
      if (programmaticScrollRef.current) return
      userScrollingRef.current = true
      clearTimeout(scrollTimerRef.current)
      scrollTimerRef.current = setTimeout(() => {
        userScrollingRef.current = false
      }, 1500)

      // Determine the rightmost visible page from scroll position and thumb width.
      // Computed arithmetically instead of iterating DOM children so it works
      // correctly after virtualization (only visible buttons are in the DOM).
      // Throttled to max once per 500 ms to prevent re-render loops triggered
      // by preview images loading and causing DOM mutation → scroll event.
      if (onScrollToPageRef.current) {
        const imgs = displayImagesRef.current
        const rightmostVisibleIndex = Math.min(
          imgs.length - 1,
          Math.ceil((el.scrollLeft + el.clientWidth) / THUMB_TOTAL_W),
        )
        const maxPage = imgs[rightmostVisibleIndex]?.pageNum ?? 1
        if (maxPage > lastScrollNotifyPageRef.current) {
          lastScrollNotifyPageRef.current = maxPage
          clearTimeout(scrollNotifyThrottleRef.current)
          scrollNotifyThrottleRef.current = setTimeout(() => {
            onScrollToPageRef.current?.(lastScrollNotifyPageRef.current)
          }, 500)
        }
      }
    }

    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault()
        el.scrollLeft += e.deltaY
      }
    }

    el.addEventListener('scroll', onScroll, { passive: true })
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      el.removeEventListener('scroll', onScroll)
      el.removeEventListener('wheel', onWheel)
      clearTimeout(scrollTimerRef.current)
      clearTimeout(scrollNotifyThrottleRef.current)
    }
  }, [])

  // Update visible range when the strip is scrolled
  useEffect(() => {
    const strip = stripRef.current
    if (!strip) return

    const updateRange = () => {
      const scrollLeft = strip.scrollLeft
      const containerWidth = strip.clientWidth
      const visibleStart = Math.floor(scrollLeft / THUMB_TOTAL_W)
      const visibleEnd = Math.ceil((scrollLeft + containerWidth) / THUMB_TOTAL_W)
      setVisibleRange({
        start: Math.max(0, visibleStart - BUFFER),
        end: Math.min(displayImages.length, visibleEnd + BUFFER),
      })
    }

    updateRange()
    strip.addEventListener('scroll', updateRange, { passive: true })
    return () => strip.removeEventListener('scroll', updateRange)
  }, [displayImages.length, THUMB_TOTAL_W, BUFFER])

  useLayoutEffect(() => {
    // NOTE: Do NOT use scrollIntoView() here. On iOS Safari (PWA and browser),
    // scrollIntoView() can scroll the entire viewport — not just the strip —
    // even with block: 'nearest'. This causes the reader UI to shift when the
    // thumbnail strip becomes visible (e.g. on Toggle Control). Instead, we
    // manually compute the target scrollLeft and assign it directly to the
    // strip container, which only scrolls the strip's own overflow, never the viewport.
    //
    // useLayoutEffect (not useEffect) is intentional: scroll must happen synchronously
    // before paint so the indicator size and the strip scroll land in the same
    // frame, preventing a visible "indicator jumps ahead of strip" jitter.
    if (userScrollingRef.current) return
    const strip = stripRef.current
    const active = activeRef.current
    if (!strip) return

    programmaticScrollRef.current = true

    if (!active) {
      // Active thumbnail is outside the virtual render window — compute scroll from index
      const activeIndex = displayImagesRef.current.findIndex((img) => img.pageNum === currentPage)
      if (activeIndex >= 0) {
        const targetScrollLeft = activeIndex * THUMB_TOTAL_W - (strip.clientWidth - 60) / 2
        strip.scrollLeft = Math.max(
          0,
          Math.min(targetScrollLeft, strip.scrollWidth - strip.clientWidth),
        )
      }
      requestAnimationFrame(() => {
        programmaticScrollRef.current = false
      })
      return
    }

    // Scroll strip to center active thumbnail
    const targetScrollLeft = active.offsetLeft - (strip.clientWidth - active.offsetWidth) / 2
    strip.scrollLeft = Math.max(
      0,
      Math.min(targetScrollLeft, strip.scrollWidth - strip.clientWidth),
    )
    // Reset flag after the scroll event has had a chance to fire
    requestAnimationFrame(() => {
      programmaticScrollRef.current = false
    })
  }, [currentPage])

  return (
    <>
      {/* Hidden imgs to load natural sprite dimensions for pixel-perfect background-size. */}
      {spriteUrls.map((proxyUrl) =>
        !spriteNaturalSizes[proxyUrl] ? (
          <img
            key={proxyUrl}
            src={proxyUrl}
            style={{ display: 'none' }}
            alt=""
            onLoad={(e) => {
              const { naturalWidth: w, naturalHeight: h } = e.currentTarget
              setSpriteNaturalSizes((prev) =>
                prev[proxyUrl] ? prev : { ...prev, [proxyUrl]: { w, h } },
              )
            }}
          />
        ) : null,
      )}
      <div
        ref={stripRef}
        className="reader-thumb-strip flex bg-black/70 px-2 backdrop-blur-sm overflow-x-auto"
        style={{
          paddingTop: THUMB_STRIP_PADDING_Y,
          paddingBottom: `calc(${THUMB_STRIP_PADDING_Y}px + env(safe-area-inset-bottom))`,
        }}
      >
        <div
          style={{
            width: displayImages.length * THUMB_TOTAL_W,
            position: 'relative',
            height: THUMB_STRIP_CELL_HEIGHT,
            flexShrink: 0,
          }}
        >
          {displayImages.slice(visibleRange.start, visibleRange.end).map((img, i) => {
            const actualIndex = visibleRange.start + i
            const isActive = img.pageNum === currentPage
            const previewRaw = previews?.[String(img.pageNum)]
            const thumbW = 60
            const thumbH = THUMB_STRIP_CELL_HEIGHT

            return (
              <div
                key={img.pageNum}
                ref={isActive ? activeRef : undefined}
                className="absolute shrink-0"
                style={{ left: actualIndex * THUMB_TOTAL_W, width: thumbW, height: thumbH, top: 0 }}
              >
                <ThumbnailCell
                  image={img}
                  isActive={isActive}
                  previewRaw={previewRaw}
                  spriteNaturalSizes={spriteNaturalSizes}
                  frameWidth={thumbW}
                  frameHeight={thumbH}
                  onSelect={onPageSelect}
                />
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}
