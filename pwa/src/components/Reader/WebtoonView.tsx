'use client'
import { useCallback, useEffect, useRef } from 'react'
import type { ReaderImage, ScaleMode } from './types'
import type { ImageLongPressHandlers } from './viewTypes'
import { WebtoonPage } from './WebtoonPage'

interface WebtoonViewProps {
  images: ReaderImage[]
  onPageChange: (page: number) => void
  onToggleOverlay: () => void
  /** When this changes and differs from the last scroll-reported page, scroll to that page. */
  scrollToPage?: number
  scaleMode: ScaleMode
  imageLongPress?: (pageNum: number, imageUrl: string) => ImageLongPressHandlers
}

export function WebtoonView({
  images,
  onPageChange,
  onToggleOverlay,
  scrollToPage,
  scaleMode,
  imageLongPress,
}: WebtoonViewProps) {
  const elRefs = useRef<Map<number, HTMLElement>>(new Map())
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastPage = images.length > 0 ? images[images.length - 1].pageNum : 0
  // Tracks the last page number reported by the IntersectionObserver (i.e. from scrolling).
  const lastReportedPage = useRef<number>(0)
  // Suppresses IntersectionObserver callbacks during programmatic scrolls to
  // prevent the observer from triggering onPageChange → fetchUpTo re-entry.
  const isProgrammaticScrollRef = useRef(false)
  const programmaticScrollTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return

    // Clean stale refs for pages no longer in the image list
    const validPages = new Set(images.map((img) => img.pageNum))
    elRefs.current.forEach((_, key) => {
      if (!validPages.has(key)) elRefs.current.delete(key)
    })

    const observer = new IntersectionObserver(
      (entries) => {
        // Ignore observer callbacks fired as a result of programmatic scrollIntoView
        if (isProgrammaticScrollRef.current) return
        let topmost: IntersectionObserverEntry | null = null
        for (const entry of entries) {
          if (entry.isIntersecting) {
            if (!topmost || entry.boundingClientRect.top < topmost.boundingClientRect.top) {
              topmost = entry
            }
          }
        }
        if (topmost) {
          const pageNum = Number((topmost.target as HTMLElement).dataset.page)
          if (!isNaN(pageNum)) {
            // Update lastReportedPage BEFORE calling onPageChange so the
            // scrollToPage effect can distinguish observer-driven changes
            // from thumbnail-click-driven changes.
            lastReportedPage.current = pageNum
            onPageChange(pageNum)
          }
        }
      },
      { threshold: 0.5 },
    )

    elRefs.current.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [images, onPageChange])

  // Scroll to a specific page when requested externally (e.g. thumbnail click).
  // Only fires when scrollToPage differs from what the observer last reported,
  // which means the change originated from outside (not from natural scrolling).
  useEffect(() => {
    if (scrollToPage != null && scrollToPage !== lastReportedPage.current) {
      const el = elRefs.current.get(scrollToPage)
      if (el) {
        // Set the flag before scrollIntoView so the IntersectionObserver
        // callbacks that fire during the scroll animation are suppressed.
        isProgrammaticScrollRef.current = true
        clearTimeout(programmaticScrollTimerRef.current)
        programmaticScrollTimerRef.current = setTimeout(() => {
          isProgrammaticScrollRef.current = false
        }, 500)
        el.scrollIntoView({ behavior: 'instant', block: 'start' })
      }
    }
  }, [scrollToPage])

  // Cleanup programmatic scroll timer on unmount
  useEffect(() => {
    return () => clearTimeout(programmaticScrollTimerRef.current)
  }, [])

  const registerPage = useCallback((pageNum: number, el: HTMLElement | null) => {
    if (el) elRefs.current.set(pageNum, el)
    else elRefs.current.delete(pageNum)
  }, [])

  const scaleClass = (() => {
    switch (scaleMode) {
      case 'fit-width':
        return 'w-full h-auto block'
      case 'fit-height':
        return 'h-screen w-auto block mx-auto'
      case 'original':
        return 'block mx-auto'
      case 'fit-both':
      default:
        return 'max-w-full max-h-screen object-contain block mx-auto'
    }
  })()

  return (
    <div
      ref={scrollRef}
      data-reader-scroll
      className="reader-webtoon-scroll flex flex-col items-center w-full h-full overflow-y-auto"
      onClick={(e) => {
        // Toggle overlay when clicking in the center zone (middle 50% width, middle 33% height)
        const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
        const x = (e.clientX - rect.left) / rect.width
        const y = (e.clientY - rect.top) / rect.height
        if (x >= 0.25 && x <= 0.75 && y >= 0.33 && y <= 0.66) {
          onToggleOverlay()
        }
      }}
    >
      {images.map((img) => (
        <WebtoonPage
          key={img.pageNum}
          image={img}
          isLast={img.pageNum === lastPage}
          scaleMode={scaleMode}
          scaleClass={scaleClass}
          register={registerPage}
          imageLongPress={imageLongPress}
        />
      ))}
    </div>
  )
}
