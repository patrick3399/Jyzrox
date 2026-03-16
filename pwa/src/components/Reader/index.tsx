'use client'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import type { GalleryImage } from '@/lib/types'
import type { ReaderImage, ViewMode, ScaleMode, ReadingDirection, ReaderSettings } from './types'
import { DEFAULT_READER_SETTINGS } from './types'
import { t } from '@/lib/i18n'
import { api } from '@/lib/api'
import { toast } from 'sonner'
import {
  useReaderState,
  useSequentialPrefetch,
  useTouchGesture,
  useKeyboardNav,
  useProgressSave,
  useAutoAdvance,
  useStatusBarClock,
  usePinchZoom,
  loadReaderSettings,
  saveReaderSettings,
} from './hooks'
import VideoPlayer from './VideoPlayer'
import { ImageContextMenu } from './ImageContextMenu'

// ── URL resolver ──────────────────────────────────────────────────────

function resolveImageUrl(image: GalleryImage, source: string, sourceId: string): string | null {
  if (image.file_path != null) {
    return image.file_path.replace('/data/', '/media/')
  }
  // Only EH has a browse-level image proxy
  if (source === 'ehentai') {
    return `/api/eh/image-proxy/${sourceId}/${image.page_num}`
  }
  // Image not yet downloaded — no proxy available
  return null
}

// ── Spinner ───────────────────────────────────────────────────────────

function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`animate-spin h-8 w-8 text-white/70 ${className}`}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  )
}

// ── Scale mode CSS helpers ────────────────────────────────────────────

function getScaleContainerClass(scaleMode: ScaleMode): string {
  switch (scaleMode) {
    case 'fit-width':
      return 'relative w-full overflow-y-auto overflow-x-hidden'
    case 'fit-height':
      return 'relative h-full overflow-x-auto overflow-y-hidden flex items-center'
    case 'original':
      return 'relative overflow-auto flex items-center justify-center'
    case 'fit-both':
    default:
      return 'relative flex h-full w-full items-center justify-center overflow-hidden'
  }
}

function getScaleImageClass(scaleMode: ScaleMode): string {
  switch (scaleMode) {
    case 'fit-width':
      return 'w-full h-auto block pointer-events-none'
    case 'fit-height':
      return 'h-screen w-auto block pointer-events-none'
    case 'original':
      return 'block pointer-events-none'
    case 'fit-both':
    default:
      return 'max-h-full max-w-full object-contain pointer-events-none'
  }
}

// ── Media element (image vs video) ───────────────────────────────────

function MediaElement({
  image,
  className,
  style,
  draggable = false,
  loading,
  dataPage,
  innerRef,
  onLoad,
  onToggleOverlay,
  overlayVisible,
}: {
  image: ReaderImage
  className?: string
  style?: React.CSSProperties
  draggable?: boolean
  loading?: 'lazy' | 'eager'
  dataPage?: number
  innerRef?: React.Ref<HTMLImageElement | HTMLVideoElement>
  onLoad?: () => void
  onToggleOverlay?: () => void
  overlayVisible?: boolean
}) {
  if (!image.url) {
    return (
      <div
        className={`flex items-center justify-center bg-black/50 ${className ?? ''}`}
        style={{ minHeight: '200px', minWidth: '200px', ...style }}
      >
        <div className="text-center text-white/50">
          <div className="mx-auto mb-2 h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-white/60" />
          <p className="text-xs">{t('reader.downloading')}</p>
        </div>
      </div>
    )
  }

  if (image.mediaType === 'video') {
    // VideoPlayer must fill its parent entirely so that the controls overlay anchors
    // to the viewport bottom, not to the middle of a shrink-wrapped box.
    // The image scale class (pointer-events-none, max-h-full, …) is designed for
    // <img> elements and must NOT be forwarded to VideoPlayer.
    return (
      <VideoPlayer
        image={image}
        className="w-full h-full"
        style={style}
        innerRef={innerRef as React.Ref<HTMLVideoElement>}
        onLoad={onLoad}
        onToggleOverlay={onToggleOverlay}
        overlayVisible={overlayVisible}
      />
    )
  }

  return (
    <img
      ref={innerRef as React.Ref<HTMLImageElement>}
      src={image.url}
      alt={`Page ${image.pageNum}`}
      className={className}
      style={style}
      draggable={draggable}
      loading={loading}
      data-page={dataPage}
      onLoad={onLoad}
    />
  )
}

// ── Props ─────────────────────────────────────────────────────────────

interface ReaderProps {
  source: string
  sourceId: string
  downloadStatus: 'proxy_only' | 'partial' | 'complete' | 'downloading'
  images: GalleryImage[]
  totalPages: number
  initialPage?: number
  /** EH preview thumbnail map: { "1": "url" or "url|ox|w|h" } */
  previews?: Record<string, string>
  /** Called when the current page changes — used by EH proxy reader for paginated token loading */
  onPageChange?: (page: number) => void
  /** Called when user seeks to a page that may not have tokens yet — triggers eager batch fetch */
  onSeekToPage?: (page: number) => Promise<void>
  /** Custom hide handler — used by artist reader where images span multiple galleries */
  onHideImage?: (pageNum: number) => Promise<void>
  /** Pre-fetched favorited image IDs from the parent page (avoids duplicate fetch) */
  initialFavoritedImageIds?: number[]
}

// ── SinglePageView ────────────────────────────────────────────────────

interface ImageLongPressHandlers {
  onTouchStart: (e: React.TouchEvent) => void
  onTouchMove: (e: React.TouchEvent) => void
  onTouchEnd: () => void
  onContextMenu: (e: React.MouseEvent) => void
}

interface SinglePageViewProps {
  image: ReaderImage
  isLoading: boolean
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
  onImageLoaded: () => void
  scaleMode: ScaleMode
  readingDirection: ReadingDirection
  showOverlay: boolean
  currentPage: number
  onZoomChange?: (isZoomed: boolean) => void
  imageLongPress?: ImageLongPressHandlers
}

function SinglePageView({
  image,
  isLoading,
  onNext,
  onPrev,
  onToggleOverlay,
  onImageLoaded,
  scaleMode,
  readingDirection,
  showOverlay,
  currentPage,
  onZoomChange,
  imageLongPress,
}: SinglePageViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // Center tap zone: delay toggle to prevent double-tap from also toggling overlay.
  // isDoubleTapRef is set by usePinchZoom's native touchstart listener (fires before any click),
  // covering both modern browsers (click fires immediately) and iOS (300ms click delay).
  const centerTapTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const isDoubleTapRef = useRef(false)
  useEffect(() => () => clearTimeout(centerTapTimerRef.current), [])
  const { isZoomed, transform, isGesturing } = usePinchZoom(
    containerRef as React.RefObject<HTMLElement | null>,
    currentPage,
    () => {
      // Called synchronously when double-tap detected — before click fires
      isDoubleTapRef.current = true
      clearTimeout(centerTapTimerRef.current)
      centerTapTimerRef.current = undefined
    },
  )

  useEffect(() => { onZoomChange?.(isZoomed) }, [isZoomed, onZoomChange])

  const leftAction = readingDirection === 'rtl' ? onNext : onPrev
  const rightAction = readingDirection === 'rtl' ? onPrev : onNext
  const isVideo = image.mediaType === 'video'

  return (
    <div
      ref={containerRef}
      className={`${getScaleContainerClass(scaleMode)} h-full w-full`}
      onTouchStart={imageLongPress?.onTouchStart}
      onTouchMove={imageLongPress?.onTouchMove}
      onTouchEnd={imageLongPress?.onTouchEnd}
      onContextMenu={imageLongPress?.onContextMenu}
    >
      <div
        style={{
          transform,
          transformOrigin: 'center center',
          transition: isGesturing ? 'none' : 'transform 0.2s ease-out',
          willChange: 'transform',
        }}
        className="w-full h-full flex items-center justify-center"
      >
        <MediaElement
          image={image}
          className={getScaleImageClass(scaleMode)}
          draggable={false}
          onLoad={onImageLoaded}
          onToggleOverlay={onToggleOverlay}
          overlayVisible={showOverlay}
        />
      </div>
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none">
          <Spinner />
        </div>
      )}
      {!isVideo && (
        <>
          {/* Center zone — always visible (even when zoomed) for overlay toggle */}
          <div
            className={`reader-tap-zone absolute cursor-pointer select-none ${readingDirection === 'vertical' ? 'top-[30%] left-0 w-full h-[40%]' : 'left-[30%] top-0 h-full w-[40%]'}`}
            onClick={(e) => {
              e.stopPropagation()
              if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
              clearTimeout(centerTapTimerRef.current)
              centerTapTimerRef.current = setTimeout(() => onToggleOverlay(), 250)
            }}
            aria-label={t('reader.toggleControls')}
          />
          {/* Prev / Next zones — hidden when zoomed (user pans instead) */}
          {!isZoomed && readingDirection === 'vertical' && (
            <>
              <div
                className="reader-tap-zone absolute top-0 left-0 w-full h-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  onPrev()
                }}
                aria-label={t('common.previousPage')}
              />
              <div
                className="reader-tap-zone absolute bottom-0 left-0 w-full h-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  onNext()
                }}
                aria-label={t('common.nextPage')}
              />
            </>
          )}
          {!isZoomed && readingDirection !== 'vertical' && (
            <>
              <div
                className="reader-tap-zone absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  leftAction()
                }}
                aria-label={readingDirection === 'rtl' ? t('common.nextPage') : t('common.previousPage')}
              />
              <div
                className="reader-tap-zone absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  rightAction()
                }}
                aria-label={readingDirection === 'rtl' ? t('common.previousPage') : t('common.nextPage')}
              />
            </>
          )}
        </>
      )}
    </div>
  )
}

// ── WebtoonView ───────────────────────────────────────────────────────

interface WebtoonViewProps {
  images: ReaderImage[]
  onPageChange: (page: number) => void
  onToggleOverlay: () => void
  /** When this changes and differs from the last scroll-reported page, scroll to that page. */
  scrollToPage?: number
  scaleMode: ScaleMode
  imageLongPress?: (pageNum: number, imageUrl: string) => ImageLongPressHandlers
}

function WebtoonView({ images, onPageChange, onToggleOverlay, scrollToPage, scaleMode, imageLongPress }: WebtoonViewProps) {
  const elRefs = useRef<Map<number, HTMLElement>>(new Map())
  const scrollRef = useRef<HTMLDivElement>(null)
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set())
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

  const handleImageLoaded = useCallback((pageNum: number) => {
    setLoadedPages((prev) => new Set([...prev, pageNum]))
  }, [])

  // Show spinner if the last visible image hasn't loaded yet
  const showBottomSpinner = lastPage > 0 && !loadedPages.has(lastPage)

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
      {images.map((img) => {
        const lpHandlers = imageLongPress && img.url ? imageLongPress(img.pageNum, img.url) : undefined
        return (
          <div
            key={img.pageNum}
            onTouchStart={lpHandlers?.onTouchStart}
            onTouchMove={lpHandlers?.onTouchMove}
            onTouchEnd={lpHandlers?.onTouchEnd}
            onContextMenu={lpHandlers?.onContextMenu}
          >
            <MediaElement
              innerRef={(el: HTMLImageElement | HTMLVideoElement | null) => {
                if (el) elRefs.current.set(img.pageNum, el)
                else elRefs.current.delete(img.pageNum)
              }}
              image={img}
              className={scaleClass}
              dataPage={img.pageNum}
              onLoad={() => handleImageLoaded(img.pageNum)}
            />
          </div>
        )
      })}
      {showBottomSpinner && (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      )}
    </div>
  )
}

// ── DoublePageView ────────────────────────────────────────────────────

interface DoublePageViewProps {
  leftImage: ReaderImage
  rightImage: ReaderImage | null
  isLoading: boolean
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
  onImageLoaded: () => void
  scaleMode: ScaleMode
  readingDirection: ReadingDirection
  showOverlay: boolean
  currentPage: number
  onZoomChange?: (isZoomed: boolean) => void
  imageLongPress?: (pageNum: number, imageUrl: string) => ImageLongPressHandlers
}

function DoublePageView({
  leftImage,
  rightImage,
  isLoading,
  onNext,
  onPrev,
  onToggleOverlay,
  onImageLoaded,
  scaleMode,
  readingDirection,
  showOverlay,
  currentPage,
  onZoomChange,
  imageLongPress,
}: DoublePageViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // Center tap zone: delay toggle to prevent double-tap from also toggling overlay.
  // isDoubleTapRef is set by usePinchZoom's native touchstart listener (fires before any click),
  // covering both modern browsers (click fires immediately) and iOS (300ms click delay).
  const centerTapTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const isDoubleTapRef = useRef(false)
  useEffect(() => () => clearTimeout(centerTapTimerRef.current), [])
  const { isZoomed, transform, isGesturing } = usePinchZoom(
    containerRef as React.RefObject<HTMLElement | null>,
    currentPage,
    () => {
      // Called synchronously when double-tap detected — before click fires
      isDoubleTapRef.current = true
      clearTimeout(centerTapTimerRef.current)
      centerTapTimerRef.current = undefined
    },
  )

  useEffect(() => { onZoomChange?.(isZoomed) }, [isZoomed, onZoomChange])

  const leftAction = readingDirection === 'rtl' ? onNext : onPrev
  const rightAction = readingDirection === 'rtl' ? onPrev : onNext

  // RTL: swap display order
  const firstImage = readingDirection === 'rtl' ? rightImage : leftImage
  const secondImage = readingDirection === 'rtl' ? leftImage : rightImage

  const imgClass = getScaleImageClass(scaleMode === 'fit-both' ? 'fit-both' : scaleMode)
  const hasVideo = leftImage?.mediaType === 'video' || rightImage?.mediaType === 'video'

  return (
    <div
      ref={containerRef}
      className="relative flex h-full w-full items-center justify-center overflow-hidden"
    >
      <div
        style={{
          transform,
          transformOrigin: 'center center',
          transition: isGesturing ? 'none' : 'transform 0.2s ease-out',
          willChange: 'transform',
        }}
        className="flex h-full w-full flex-row"
      >
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          {firstImage ? (() => {
            const lp = imageLongPress && firstImage.url ? imageLongPress(firstImage.pageNum, firstImage.url) : undefined
            return (
              <div
                className="w-full h-full flex items-center justify-center"
                onTouchStart={lp?.onTouchStart}
                onTouchMove={lp?.onTouchMove}
                onTouchEnd={lp?.onTouchEnd}
                onContextMenu={lp?.onContextMenu}
              >
                <MediaElement
                  image={firstImage}
                  className={imgClass}
                  draggable={false}
                  onLoad={onImageLoaded}
                  onToggleOverlay={onToggleOverlay}
                  overlayVisible={showOverlay}
                />
              </div>
            )
          })() : (
            <div className="h-full w-full" />
          )}
        </div>
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          {secondImage ? (() => {
            const lp = imageLongPress && secondImage.url ? imageLongPress(secondImage.pageNum, secondImage.url) : undefined
            return (
              <div
                className="w-full h-full flex items-center justify-center"
                onTouchStart={lp?.onTouchStart}
                onTouchMove={lp?.onTouchMove}
                onTouchEnd={lp?.onTouchEnd}
                onContextMenu={lp?.onContextMenu}
              >
                <MediaElement
                  image={secondImage}
                  className={imgClass}
                  draggable={false}
                  onLoad={onImageLoaded}
                  onToggleOverlay={onToggleOverlay}
                  overlayVisible={showOverlay}
                />
              </div>
            )
          })() : (
            <div className="h-full w-full" />
          )}
        </div>
      </div>
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none">
          <Spinner />
        </div>
      )}
      {!hasVideo && (
        <>
          {/* Center zone — always visible (even when zoomed) for overlay toggle */}
          <div
            className={`reader-tap-zone absolute cursor-pointer select-none ${readingDirection === 'vertical' ? 'top-[30%] left-0 w-full h-[40%]' : 'left-[30%] top-0 h-full w-[40%]'}`}
            onClick={(e) => {
              e.stopPropagation()
              if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
              clearTimeout(centerTapTimerRef.current)
              centerTapTimerRef.current = setTimeout(() => onToggleOverlay(), 250)
            }}
            aria-label={t('reader.toggleControls')}
          />
          {/* Prev / Next zones — hidden when zoomed (user pans instead) */}
          {!isZoomed && readingDirection === 'vertical' && (
            <>
              <div
                className="reader-tap-zone absolute top-0 left-0 w-full h-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  onPrev()
                }}
                aria-label={t('common.previousPage')}
              />
              <div
                className="reader-tap-zone absolute bottom-0 left-0 w-full h-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  onNext()
                }}
                aria-label={t('common.nextPage')}
              />
            </>
          )}
          {!isZoomed && readingDirection !== 'vertical' && (
            <>
              <div
                className="reader-tap-zone absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  leftAction()
                }}
                aria-label={readingDirection === 'rtl' ? t('common.nextPage') : t('common.previousPage')}
              />
              <div
                className="reader-tap-zone absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) { isDoubleTapRef.current = false; return }
                  rightAction()
                }}
                aria-label={readingDirection === 'rtl' ? t('common.previousPage') : t('common.nextPage')}
              />
            </>
          )}
        </>
      )}
    </div>
  )
}

// ── ReaderOverlay ─────────────────────────────────────────────────────

interface ReaderOverlayProps {
  currentPage: number
  totalPages: number
  viewMode: ViewMode
  scaleMode: ScaleMode
  readingDirection: ReadingDirection
  autoAdvanceEnabled: boolean
  autoAdvanceSeconds: number
  onBack: () => void
  onViewModeChange: (mode: ViewMode) => void
  onScaleModeChange: (mode: ScaleMode) => void
  onReadingDirectionChange: (dir: ReadingDirection) => void
  onAutoAdvanceToggle: () => void
  onAutoAdvanceIntervalChange: (s: number) => void
  onShowHelp: () => void
  onPageSelect: (page: number) => void
}

function ReaderOverlay({
  currentPage,
  totalPages,
  viewMode,
  scaleMode,
  readingDirection,
  autoAdvanceEnabled,
  autoAdvanceSeconds,
  onBack,
  onViewModeChange,
  onScaleModeChange,
  onReadingDirectionChange,
  onAutoAdvanceToggle,
  onAutoAdvanceIntervalChange,
  onShowHelp,
  onPageSelect,
}: ReaderOverlayProps) {
  const VIEW_MODES: { mode: ViewMode; icon: string; label: string }[] = [
    { mode: 'single', icon: '▣', label: t('reader.viewModeSingleShort') },
    { mode: 'webtoon', icon: '▥', label: t('reader.viewModeWebtoonShort') },
    { mode: 'double', icon: '◫', label: t('reader.viewModeDoubleShort') },
  ]

  const SCALE_MODES: { mode: ScaleMode; icon: string; label: string }[] = [
    { mode: 'fit-both', icon: '⊞', label: t('reader.scaleFitBothShort') },
    { mode: 'fit-width', icon: '↔', label: t('reader.scaleFitWidthShort') },
    { mode: 'fit-height', icon: '↕', label: t('reader.scaleFitHeightShort') },
    { mode: 'original', icon: '1:1', label: t('reader.scaleOriginalShort') },
  ]

  const DIRECTIONS: { dir: ReadingDirection; icon: string; label: string }[] = [
    { dir: 'ltr', icon: '→', label: t('reader.dirLtrShort') },
    { dir: 'rtl', icon: '←', label: t('reader.dirRtlShort') },
    { dir: 'vertical', icon: '↓', label: t('reader.dirVerticalShort') },
  ]

  const cycleViewMode = () => {
    const idx = VIEW_MODES.findIndex((v) => v.mode === viewMode)
    onViewModeChange(VIEW_MODES[(idx + 1) % VIEW_MODES.length].mode)
  }

  const cycleScaleMode = () => {
    const idx = SCALE_MODES.findIndex((s) => s.mode === scaleMode)
    onScaleModeChange(SCALE_MODES[(idx + 1) % SCALE_MODES.length].mode)
  }

  const cycleDirection = () => {
    const idx = DIRECTIONS.findIndex((d) => d.dir === readingDirection)
    onReadingDirectionChange(DIRECTIONS[(idx + 1) % DIRECTIONS.length].dir)
  }

  const currentView = VIEW_MODES.find((v) => v.mode === viewMode) ?? VIEW_MODES[0]
  const currentScale = SCALE_MODES.find((s) => s.mode === scaleMode) ?? SCALE_MODES[0]
  const currentDir = DIRECTIONS.find((d) => d.dir === readingDirection) ?? DIRECTIONS[0]

  const cycleBtnClass =
    'w-10 h-10 rounded text-lg font-medium transition-colors bg-white/10 hover:bg-white/20 text-white border border-white/20 flex items-center justify-center shrink-0'

  // Page jump dialog
  const [showJump, setShowJump] = useState(false)
  const [jumpInput, setJumpInput] = useState('')
  const jumpInputRef = useRef<HTMLInputElement>(null)

  const openJump = () => {
    setJumpInput(String(currentPage))
    setShowJump(true)
  }

  const closeJump = () => setShowJump(false)

  const commitJump = () => {
    const page = parseInt(jumpInput, 10)
    if (!isNaN(page) && page >= 1 && page <= totalPages) {
      onPageSelect(page)
    }
    closeJump()
  }

  useEffect(() => {
    if (showJump) {
      // Only auto-focus on non-touch devices; on mobile, focusing triggers
      // the soft keyboard which shifts the iOS visual viewport.
      const isTouch = window.matchMedia('(pointer: coarse)').matches
      if (isTouch) return
      const t = setTimeout(() => jumpInputRef.current?.select(), 50)
      return () => clearTimeout(t)
    }
  }, [showJump])

  useEffect(() => {
    if (!showJump) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeJump()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [showJump])

  return (
    <div
      className="bg-black/70 text-white text-sm backdrop-blur-sm"
      style={{ paddingTop: 'min(env(safe-area-inset-top), 45px)' }}
    >
      {/* Row 1: page indicator · cycle buttons (left-aligned) · auto-advance toggle · help · close */}
      <div className="flex items-center gap-2 px-4 py-2">
        {/* Page indicator */}
        <div className="relative">
          <button
            onClick={openJump}
            className="font-mono tabular-nums whitespace-nowrap text-xs bg-white/10 hover:bg-white/20 rounded px-1.5 py-0.5 transition-colors"
            title={t('reader.jumpToPage')}
          >
            {currentPage} / {totalPages}
          </button>
          {showJump && (
            <>
              <div className="fixed inset-0 z-30" onClick={closeJump} />
              <div className="absolute top-full left-0 mt-1 z-40 bg-black/90 border border-white/20 rounded-lg p-3 flex items-center gap-2 shadow-xl min-w-[140px]">
                <input
                  ref={jumpInputRef}
                  type="number"
                  min={1}
                  max={totalPages}
                  value={jumpInput}
                  onChange={(e) => setJumpInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitJump()
                    else if (e.key === 'Escape') closeJump()
                    e.stopPropagation()
                  }}
                  className="w-16 bg-white/10 border border-white/20 rounded px-2 py-1 text-xs text-white text-center tabular-nums focus:outline-none focus:border-white/50"
                />
                <button
                  onClick={commitJump}
                  className="bg-white text-black rounded px-2 py-1 text-xs font-medium hover:bg-white/90 shrink-0"
                >
                  Go
                </button>
              </div>
            </>
          )}
        </div>

        {/* Cycle buttons immediately after page indicator */}
        <button onClick={cycleViewMode} className={cycleBtnClass} title={currentView.label}>
          <span>{currentView.icon}</span>
        </button>
        <button onClick={cycleScaleMode} className={cycleBtnClass} title={currentScale.label}>
          <span>{currentScale.icon}</span>
        </button>
        {viewMode !== 'webtoon' && (
          <button onClick={cycleDirection} className={cycleBtnClass} title={currentDir.label}>
            <span>{currentDir.icon}</span>
          </button>
        )}

        <div className="flex-1" />

        {/* Auto advance toggle only (slider in Row 2 when enabled) */}
        <button
          onClick={onAutoAdvanceToggle}
          className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${autoAdvanceEnabled ? 'bg-vault-accent' : 'bg-white/20'}`}
          aria-label={t('reader.autoAdvance')}
          title={t('reader.autoAdvance')}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${autoAdvanceEnabled ? 'translate-x-4' : ''}`}
          />
        </button>

        {/* Help + Close */}
        <button
          onClick={onShowHelp}
          className="w-10 h-10 rounded bg-white/10 hover:bg-white/20 border border-white/20 text-white/80 hover:text-white transition-colors flex items-center justify-center shrink-0"
          title={t('reader.helpButton')}
        >
          ?
        </button>
        <button
          onClick={onBack}
          className="w-10 h-10 rounded bg-red-600 hover:bg-red-500 text-white font-bold transition-colors flex items-center justify-center shrink-0"
          title={t('reader.goBack')}
        >
          ✕
        </button>
      </div>

      {/* Row 2: auto advance slider — only shown when enabled */}
      {autoAdvanceEnabled && (
        <div className="flex items-center gap-2 px-4 pb-2">
          <span className="text-[11px] text-white/60 shrink-0">{t('reader.autoAdvance')}</span>
          <input
            type="range"
            min={2}
            max={30}
            step={1}
            value={autoAdvanceSeconds}
            onChange={(e) => onAutoAdvanceIntervalChange(Number(e.target.value))}
            className="flex-1 accent-white"
          />
          <span className="text-[11px] tabular-nums whitespace-nowrap w-6 text-right">
            {autoAdvanceSeconds}s
          </span>
        </div>
      )}
    </div>
  )
}

// ── ThumbnailStrip ────────────────────────────────────────────────────

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

function ThumbnailStrip({
  images,
  currentPage,
  onPageSelect,
  previews,
  onScrollToPage,
  isVisible,
  readingDirection,
}: ThumbnailStripProps) {
  const activeRef = useRef<HTMLButtonElement | null>(null)
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
    () => readingDirection === 'rtl' ? [...images].reverse() : images,
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
          Math.ceil((el.scrollLeft + el.clientWidth) / THUMB_TOTAL_W)
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
      const activeIndex = displayImagesRef.current.findIndex(img => img.pageNum === currentPage)
      if (activeIndex >= 0) {
        const targetScrollLeft = activeIndex * THUMB_TOTAL_W - (strip.clientWidth - 60) / 2
        strip.scrollLeft = Math.max(0, Math.min(targetScrollLeft, strip.scrollWidth - strip.clientWidth))
      }
      requestAnimationFrame(() => { programmaticScrollRef.current = false })
      return
    }

    // Scroll strip to center active thumbnail
    const targetScrollLeft = active.offsetLeft - (strip.clientWidth - active.offsetWidth) / 2
    strip.scrollLeft = Math.max(0, Math.min(targetScrollLeft, strip.scrollWidth - strip.clientWidth))
    // Reset flag after the scroll event has had a chance to fire
    requestAnimationFrame(() => { programmaticScrollRef.current = false })
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
        className="reader-thumb-strip flex bg-black/70 px-2 py-2 backdrop-blur-sm overflow-x-auto"
        style={{ paddingBottom: 'calc(8px + env(safe-area-inset-bottom))' }}
      >
        <div style={{ width: displayImages.length * THUMB_TOTAL_W, position: 'relative', height: 80, flexShrink: 0 }}>
          {displayImages.slice(visibleRange.start, visibleRange.end).map((img, i) => {
            const actualIndex = visibleRange.start + i
            const isActive = img.pageNum === currentPage
            const previewRaw = previews?.[String(img.pageNum)]

            let thumbSrc: string | null = null
            let spriteStyle: React.CSSProperties | null = null
            let thumbW = 60
            let thumbH = 80

            if (previewRaw) {
              if (previewRaw.includes('|')) {
                const parts = previewRaw.split('|')
                const spriteUrl = parts[0]
                const ox = Number(parts[1])
                const cellW = Number(parts[2]) || 200
                const cellH = Number(parts[3]) || 300
                const maxH = 80
                const maxW = 100
                const scaleByH = maxH / cellH
                const scaleByW = maxW / cellW
                const scale = Math.min(scaleByH, scaleByW)
                const renderedW = Math.round(cellW * scale)
                const renderedH = Math.round(cellH * scale)
                thumbW = renderedW
                thumbH = renderedH
                const scaledOx = ox * scale
                const proxyUrl = `/api/eh/thumb-proxy?url=${encodeURIComponent(spriteUrl)}`
                const naturalSize = spriteNaturalSizes[proxyUrl]
                const bgSize = naturalSize
                  ? `${naturalSize.w * scale}px ${naturalSize.h * scale}px`
                  : `auto ${cellH * scale}px`
                spriteStyle = {
                  backgroundImage: `url(${proxyUrl})`,
                  backgroundPosition: `${scaledOx}px 0px`,
                  backgroundSize: bgSize,
                  backgroundRepeat: 'no-repeat',
                  width: '100%',
                  height: '100%',
                }
              } else {
                thumbSrc = `/api/eh/thumb-proxy?url=${encodeURIComponent(previewRaw)}`
              }
            } else if (img.isLocal) {
              thumbSrc = img.thumbUrl || img.url
            }

            return (
              <button
                key={img.pageNum}
                ref={isActive ? activeRef : null}
                onClick={() => onPageSelect(img.pageNum)}
                className={`absolute shrink-0 overflow-hidden rounded ${
                  isActive ? 'ring-2 ring-white opacity-100' : 'opacity-50 hover:opacity-80'
                }`}
                style={{ left: actualIndex * THUMB_TOTAL_W, width: thumbW, height: thumbH, top: 0 }}
                title={`Page ${img.pageNum}`}
              >
                {spriteStyle ? (
                  <div style={spriteStyle} />
                ) : thumbSrc ? (
                  <img
                    src={thumbSrc}
                    alt={`Thumb ${img.pageNum}`}
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <div className="h-full w-full bg-neutral-800 flex items-center justify-center">
                    <span className="text-[11px] text-gray-500">{img.pageNum}</span>
                  </div>
                )}
                <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-center text-[10px] text-white leading-tight py-px">
                  {img.pageNum}
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </>
  )
}

// ── SeekBar ───────────────────────────────────────────────────────────

function SeekBar({
  currentPage,
  totalPages,
  onSeek,
  readingDirection,
}: {
  currentPage: number
  totalPages: number
  onSeek: (page: number) => void
  readingDirection?: 'ltr' | 'rtl' | 'vertical'
}) {
  const barRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  const [previewPage, setPreviewPage] = useState<number | null>(null)
  const draggingRef = useRef(false)

  const isRtl = readingDirection === 'rtl'
  const getPageFromX = useCallback(
    (clientX: number) => {
      if (!barRef.current) return currentPage
      const rect = barRef.current.getBoundingClientRect()
      let ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      if (isRtl) ratio = 1 - ratio
      return Math.max(1, Math.round(ratio * totalPages))
    },
    [currentPage, totalPages, isRtl],
  )

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    onSeek(getPageFromX(e.clientX))
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation()
    draggingRef.current = true
    setDragging(true)
    setPreviewPage(getPageFromX(e.clientX))
    e.preventDefault()
  }

  useEffect(() => {
    if (!dragging) return
    const handleMouseMove = (e: MouseEvent) => {
      if (draggingRef.current) setPreviewPage(getPageFromX(e.clientX))
    }
    const handleMouseUp = (e: MouseEvent) => {
      if (draggingRef.current) {
        const page = getPageFromX(e.clientX)
        onSeek(page)
      }
      draggingRef.current = false
      setDragging(false)
      setPreviewPage(null)
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [dragging, getPageFromX, onSeek])

  const handleTouchStart = (e: React.TouchEvent) => {
    e.stopPropagation()
    draggingRef.current = true
    setDragging(true)
    setPreviewPage(getPageFromX(e.touches[0].clientX))
  }

  const handleTouchMove = (e: React.TouchEvent) => {
    e.stopPropagation()
    if (draggingRef.current) setPreviewPage(getPageFromX(e.touches[0].clientX))
  }

  const handleTouchEnd = (e: React.TouchEvent) => {
    e.stopPropagation()
    if (previewPage != null) onSeek(previewPage)
    draggingRef.current = false
    setDragging(false)
    setPreviewPage(null)
  }

  const displayPage = previewPage ?? currentPage
  const progress = totalPages > 1 ? ((displayPage - 1) / (totalPages - 1)) * 100 : 0

  return (
    <div
      ref={barRef}
      className="flex-1 relative cursor-pointer py-2 -my-2 select-none"
      onClick={handleClick}
      onMouseDown={handleMouseDown}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      <div className="h-1.5 rounded-full bg-white/20 relative">
        <div
          className="h-full rounded-full bg-white/70"
          style={isRtl ? { width: `${progress}%`, marginLeft: 'auto' } : { width: `${progress}%` }}
        />
        <div
          className="absolute w-3 h-3 rounded-full bg-white shadow"
          style={isRtl
            ? { right: `${progress}%`, top: '50%', transform: 'translate(50%, -50%)' }
            : { left: `${progress}%`, top: '50%', transform: 'translate(-50%, -50%)' }
          }
        />
      </div>
      {previewPage != null && (
        <div
          className="absolute -top-8 bg-black/80 text-white text-xs px-2 py-1 rounded pointer-events-none"
          style={isRtl
            ? { right: `${progress}%`, transform: 'translateX(50%)' }
            : { left: `${progress}%`, transform: 'translateX(-50%)' }
          }
        >
          {previewPage}
        </div>
      )}
    </div>
  )
}

// ── StatusBar ─────────────────────────────────────────────────────────

interface StatusBarProps {
  currentPage: number
  totalPages: number
  settings: ReaderSettings
  countdown: number
  autoAdvanceEnabled: boolean
  onPageSelect: (page: number) => void
  readingDirection?: 'ltr' | 'rtl' | 'vertical'
}

function StatusBar({
  currentPage,
  totalPages,
  settings,
  countdown,
  autoAdvanceEnabled,
  onPageSelect,
  readingDirection,
}: StatusBarProps) {
  const clock = useStatusBarClock(settings.statusBarEnabled && settings.statusBarShowClock)

  if (!settings.statusBarEnabled) return null

  return (
    <div
      className="reader-status-bar flex items-center gap-3 px-3"
      style={{ height: 24, background: 'rgba(0,0,0,0.55)' }}
    >
      {settings.statusBarShowClock && clock && (
        <span className="text-[11px] text-white/80 tabular-nums shrink-0">{clock}</span>
      )}

      {settings.statusBarShowProgress && (
        <SeekBar currentPage={currentPage} totalPages={totalPages} onSeek={onPageSelect} readingDirection={readingDirection} />
      )}

      {settings.statusBarShowPageCount && (
        <span className="text-[11px] text-white/80 tabular-nums shrink-0">
          {currentPage} / {totalPages}
        </span>
      )}

      {autoAdvanceEnabled && (
        <span className="text-[11px] text-white/60 tabular-nums shrink-0">{countdown}s</span>
      )}
    </div>
  )
}

// ── HelpOverlay ───────────────────────────────────────────────────────

interface HelpOverlayProps {
  readingDirection: ReadingDirection
  viewMode: ViewMode
  onDismiss: () => void
}

function HelpOverlay({ readingDirection, viewMode, onDismiss }: HelpOverlayProps) {
  const isRtl = readingDirection === 'rtl'
  const isVertical = readingDirection === 'vertical'

  const leftLabel = isRtl ? t('reader.helpTapRight') : t('reader.helpTapLeft')
  const rightLabel = isRtl ? t('reader.helpTapLeft') : t('reader.helpTapRight')

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      onDismiss()
      e.stopPropagation()
    }
    window.addEventListener('keydown', handler, { once: true })
    return () => window.removeEventListener('keydown', handler)
  }, [onDismiss])

  return (
    <div className="absolute inset-0 z-50 flex flex-col" onClick={onDismiss}>
      {viewMode === 'webtoon' ? (
        /* Webtoon mode: only center tap zone */
        <div className="flex flex-1 items-center justify-center bg-white/5">
          <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
        </div>
      ) : isVertical ? (
        /* Vertical direction: top/middle/bottom zones */
        <div className="flex flex-col flex-1">
          <div className="h-[30%] w-full flex items-center justify-center bg-blue-500/20 border-b border-blue-400/30">
            <div className="text-white text-sm font-medium">{t('reader.helpTapLeft')}</div>
          </div>
          <div className="flex-1 w-full flex items-center justify-center bg-white/5 border-b border-white/10">
            <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
          </div>
          <div className="h-[30%] w-full flex items-center justify-center bg-green-500/20">
            <div className="text-white text-sm font-medium">{t('reader.helpTapRight')}</div>
          </div>
        </div>
      ) : (
        /* Horizontal direction: left/center/right zones */
        <div className="flex flex-1">
          <div className="w-[30%] h-full flex items-center justify-center bg-blue-500/20 border-r border-blue-400/30">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{leftLabel}</div>
            </div>
          </div>
          <div className="flex-1 h-full flex items-center justify-center bg-white/5 border-r border-white/10">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
            </div>
          </div>
          <div className="w-[30%] h-full flex items-center justify-center bg-green-500/20">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{rightLabel}</div>
            </div>
          </div>
        </div>
      )}

      {/* Bottom info */}
      <div className="absolute bottom-20 left-0 right-0 flex flex-col items-center gap-2 pointer-events-none">
        <div className="bg-black/80 rounded-lg px-4 py-3 text-center space-y-1.5 max-w-sm">
          {viewMode === 'webtoon' ? (
            <p className="text-white text-sm">{t('reader.helpSwipeRight')}</p>
          ) : (
            <>
              <p className="text-white text-sm">{t('reader.helpSwipe')}</p>
              <p className="text-white/70 text-xs">{t('reader.helpSwipeUp')}</p>
            </>
          )}
          <p className="text-white/70 text-xs">{t('reader.helpDoubleTap')}</p>
          <p className="text-white/70 text-xs">{t('reader.helpPinchZoom')}</p>
          <p className="text-white/60 text-xs">{t('reader.helpKeyboard')}</p>
          <p className="text-white/40 text-xs">{t('reader.helpDismiss')}</p>
        </div>
      </div>
    </div>
  )
}

// ── Reader (main component) ───────────────────────────────────────────

export default function Reader({
  source,
  sourceId,
  downloadStatus,
  images: rawImages,
  totalPages,
  initialPage = 1,
  previews,
  onPageChange,
  onSeekToPage,
  onHideImage,
  initialFavoritedImageIds,
}: ReaderProps) {
  const router = useRouter()
  const isProxyMode = downloadStatus === 'proxy_only'

  const [hiddenPages, setHiddenPages] = useState<Set<number>>(new Set())
  const [favImageIds, setFavImageIds] = useState<Set<number>>(
    () => new Set(initialFavoritedImageIds ?? [])
  )

  const images: ReaderImage[] = rawImages
    .filter((img) => !hiddenPages.has(img.page_num))
    .map((img) => ({
      pageNum: img.page_num,
      url: resolveImageUrl(img, source, sourceId),
      isLocal: img.file_path != null,
      width: img.width ?? undefined,
      height: img.height ?? undefined,
      mediaType: img.media_type,
      duration: img.duration ?? undefined,
      thumbUrl: img.thumb_path?.replace('/data/', '/media/') ?? undefined,
    }))

  const {
    state,
    setPage,
    nextPage: rawNextPage,
    prevPage: rawPrevPage,
    setViewMode,
    toggleOverlay,
    setScaleMode,
    setReadingDirection,
  } = useReaderState(initialPage, totalPages, source, sourceId)

  // Reading direction aware next/prev
  const nextPage = useCallback(() => {
    if (state.readingDirection === 'rtl') {
      rawPrevPage()
    } else {
      rawNextPage()
    }
  }, [state.readingDirection, rawNextPage, rawPrevPage])

  const prevPage = useCallback(() => {
    if (state.readingDirection === 'rtl') {
      rawNextPage()
    } else {
      rawPrevPage()
    }
  }, [state.readingDirection, rawNextPage, rawPrevPage])

  // Reader settings (status bar, auto advance)
  const [readerSettings, setReaderSettings] = useState<ReaderSettings>(DEFAULT_READER_SETTINGS)
  useEffect(() => {
    setReaderSettings(loadReaderSettings())
  }, [])

  // Auto advance local state (overlay controls)
  const [autoAdvanceEnabled, setAutoAdvanceEnabled] = useState(false)
  const [autoAdvanceSeconds, setAutoAdvanceSeconds] = useState(5)

  useEffect(() => {
    const s = loadReaderSettings()
    setAutoAdvanceEnabled(s.autoAdvanceEnabled)
    setAutoAdvanceSeconds(s.autoAdvanceSeconds)
  }, [])

  const effectiveTotalPages = totalPages - hiddenPages.size
  const isLastPage = images.length > 0
    ? state.currentPage >= images[images.length - 1].pageNum
    : true

  const { countdown, resetCountdown } = useAutoAdvance(
    autoAdvanceEnabled,
    autoAdvanceSeconds,
    rawNextPage,
    isLastPage,
  )

  // Reset countdown on manual page change
  useEffect(() => {
    resetCountdown()
  }, [state.currentPage, resetCountdown])

  const containerRef = useRef<HTMLDivElement>(null)

  // Prevent background scroll while Reader is mounted.
  // IMPORTANT: Do NOT set body.position=fixed — on iOS Safari, that makes
  // child position:fixed elements behave as position:absolute relative to body.
  useEffect(() => {
    const html = document.documentElement
    const body = document.body
    html.style.overflow = 'hidden'
    body.style.overflow = 'hidden'

    // iOS 15+: toolbar show/hide changes layout viewport height.
    // Lock height to the LARGEST observed value so toolbar appearing never collapses the reader.
    // On toolbar hide (viewport expands), we update to the new larger height.
    const el = containerRef.current
    if (el) {
      el.style.height = `${window.innerHeight}px`
      const onResize = () => {
        const h = window.innerHeight
        const current = parseInt(el.style.height || '0', 10)
        if (h > current) el.style.height = `${h}px`
      }
      window.addEventListener('resize', onResize)
      return () => {
        html.style.overflow = ''
        body.style.overflow = ''
        el.style.height = ''
        window.removeEventListener('resize', onResize)
      }
    }

    return () => {
      html.style.overflow = ''
      body.style.overflow = ''
    }
  }, [])

  // Track image loading state for single/double page views
  const [pageLoading, setPageLoading] = useState(false)
  const loadingPageRef = useRef(state.currentPage)
  const loadedPagesRef = useRef<Set<number>>(new Set())
  const loadingTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const handleImageLoaded = useCallback(() => {
    loadedPagesRef.current.add(state.currentPage)
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current)
      loadingTimerRef.current = undefined
    }
    setPageLoading(false)
  }, [state.currentPage])

  // When page changes, start a short timer before showing the spinner.
  // If the image loads before the timer fires (onLoad clears the timer), the spinner never appears.
  // Key fix: check if the page was already loaded (onLoad fired before this effect ran).
  useEffect(() => {
    if (state.viewMode !== 'webtoon' && state.currentPage !== loadingPageRef.current) {
      loadingPageRef.current = state.currentPage

      // If onLoad already fired for this page before this effect ran, skip the spinner
      if (loadedPagesRef.current.has(state.currentPage)) {
        loadedPagesRef.current.delete(state.currentPage)
        setPageLoading(false)
        return
      }

      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current)
      loadingTimerRef.current = setTimeout(() => {
        setPageLoading(true)
      }, 150)
    }
  }, [state.currentPage, state.viewMode])

  // Cleanup loading timer on unmount
  useEffect(() => {
    return () => {
      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current)
    }
  }, [])

  // Notify parent of page changes (used for paginated token loading in EH proxy mode)
  useEffect(() => {
    onPageChange?.(state.currentPage)
  }, [state.currentPage, onPageChange])

  // Wrapped setPage that also triggers eager token fetch for large jumps
  const setPageWithPrefetch = useCallback(
    (page: number) => {
      setPage(page)
      onSeekToPage?.(page)
    },
    [setPage, onSeekToPage],
  )

  useSequentialPrefetch(images, state.currentPage, isProxyMode)
  useProgressSave(source, sourceId, state.currentPage)

  const handleToggleOverlay = useCallback(() => toggleOverlay(), [toggleOverlay])
  const handleBack = useCallback(() => router.back(), [router])

  // Track viewMode in ref so swipe callbacks stay stable across mode changes
  const viewModeRef = useRef(state.viewMode)
  useEffect(() => { viewModeRef.current = state.viewMode }, [state.viewMode])

  // Swipe: respect RTL direction; in webtoon mode, swipeRight = go back
  const swipeLeft = useCallback(() => {
    if (state.readingDirection === 'rtl') rawPrevPage()
    else rawNextPage()
  }, [state.readingDirection, rawNextPage, rawPrevPage])

  const swipeRight = useCallback(() => {
    if (viewModeRef.current === 'webtoon') { handleBack(); return }
    if (state.readingDirection === 'rtl') rawNextPage()
    else rawPrevPage()
  }, [state.readingDirection, rawNextPage, rawPrevPage, handleBack])

  const handleSwipeUp = useCallback(() => {
    if (viewModeRef.current !== 'webtoon') handleBack()
  }, [handleBack])

  const isZoomedRef = useRef(false)
  const handleZoomChange = useCallback((z: boolean) => { isZoomedRef.current = z }, [])

  useTouchGesture(containerRef as React.RefObject<HTMLElement | null>, swipeLeft, swipeRight, handleSwipeUp, 50, () => isZoomedRef.current)

  useKeyboardNav(rawNextPage, rawPrevPage, handleToggleOverlay, handleBack, state.readingDirection, state.viewMode)

  // Mouse wheel: scroll down → next page, scroll up → prev page (single/double only)
  // Webtoon mode uses native continuous scrolling (like mobile touch)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    if (state.viewMode === 'webtoon') return
    let cooldown = false
    const handler = (e: WheelEvent) => {
      // Don't intercept wheel events on the thumbnail strip (it has its own horizontal scroll)
      if ((e.target as HTMLElement)?.closest('.reader-thumb-strip')) return
      // Don't intercept wheel events on the overlay controls
      if ((e.target as HTMLElement)?.closest('.reader-overlay')) return
      if (cooldown) return
      const dy = e.deltaY
      if (Math.abs(dy) < 10) return
      e.preventDefault()
      cooldown = true
      setTimeout(() => { cooldown = false }, 200)
      if (dy > 0) rawNextPage()
      else rawPrevPage()
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [rawNextPage, rawPrevPage, state.viewMode])

  // Escape key to go back
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        router.back()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [router])

  // Help overlay
  const [showHelp, setShowHelp] = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const shown = localStorage.getItem('reader_help_shown')
    if (!shown) {
      setShowHelp(true)
      localStorage.setItem('reader_help_shown', '1')
    }
  }, [])

  const handleDismissHelp = useCallback(() => setShowHelp(false), [])
  const handleShowHelp = useCallback(() => setShowHelp(true), [])

  // ── Image long-press / context menu ───────────────────────────────────
  const [imageMenu, setImageMenu] = useState<{
    open: boolean
    position: { x: number; y: number }
    imageUrl: string
    imageName: string
    pageNum: number
  } | null>(null)

  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const longPressStartRef = useRef<{ x: number; y: number } | null>(null)

  const makeImageLongPressHandlers = useCallback(
    (imageUrl: string, imageName: string, pageNum: number): ImageLongPressHandlers => ({
      onTouchStart: (e: React.TouchEvent) => {
        const touch = e.touches[0]
        longPressStartRef.current = { x: touch.clientX, y: touch.clientY }
        longPressTimerRef.current = setTimeout(() => {
          setImageMenu({
            open: true,
            position: { x: touch.clientX, y: touch.clientY },
            imageUrl,
            imageName,
            pageNum,
          })
        }, 500)
      },
      onTouchMove: (e: React.TouchEvent) => {
        if (!longPressStartRef.current || !longPressTimerRef.current) return
        const touch = e.touches[0]
        const dx = touch.clientX - longPressStartRef.current.x
        const dy = touch.clientY - longPressStartRef.current.y
        if (Math.sqrt(dx * dx + dy * dy) > 10) {
          clearTimeout(longPressTimerRef.current)
          longPressTimerRef.current = null
        }
      },
      onTouchEnd: () => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current)
          longPressTimerRef.current = null
        }
      },
      onContextMenu: (e: React.MouseEvent) => {
        e.preventDefault()
        setImageMenu({
          open: true,
          position: { x: e.clientX, y: e.clientY },
          imageUrl,
          imageName,
          pageNum,
        })
      },
    }),
    [],
  )

  // Helper used by SinglePageView (single image, known at call site)
  const makeSinglePageHandlers = useCallback(
    (image: ReaderImage): ImageLongPressHandlers | undefined => {
      if (!image.url) return undefined
      return makeImageLongPressHandlers(image.url, `page_${image.pageNum}`, image.pageNum)
    },
    [makeImageLongPressHandlers],
  )

  // Helper used by WebtoonView / DoublePageView (page num + url supplied per-image)
  const makePerImageHandlers = useCallback(
    (pageNum: number, imageUrl: string): ImageLongPressHandlers =>
      makeImageLongPressHandlers(imageUrl, `page_${pageNum}`, pageNum),
    [makeImageLongPressHandlers],
  )

  // Clean up long-press timer on unmount
  useEffect(() => {
    return () => {
      if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current)
    }
  }, [])

  const handleHideImage = useCallback(async () => {
    if (!imageMenu) return
    const { pageNum } = imageMenu

    // Close menu first so the confirm dialog appears without the menu behind it
    setImageMenu(null)

    if (!window.confirm(t('reader.hideImageConfirm'))) return

    try {
      if (onHideImage) {
        await onHideImage(pageNum)
      } else {
        await api.library.deleteImage(source, sourceId, pageNum)
      }
      toast.success(t('reader.imageHidden'))

      // Compute remaining images after this hide (hiddenPages state not yet updated)
      const remainingImages = rawImages.filter(
        (img) => !hiddenPages.has(img.page_num) && img.page_num !== pageNum,
      )

      if (remainingImages.length === 0) {
        // All images hidden — leave the reader
        router.back()
        return
      }

      // If the current page is the one being hidden, navigate to the nearest available page
      if (state.currentPage === pageNum) {
        const nextAvailable =
          remainingImages.find((img) => img.page_num > pageNum) ??
          remainingImages[remainingImages.length - 1]
        if (nextAvailable) {
          setPage(nextAvailable.page_num)
        }
      }

      // Update local state to remove the hidden image instantly
      setHiddenPages((prev) => new Set(prev).add(pageNum))
    } catch {
      toast.error(t('reader.hideImageFailed'))
    }
  }, [imageMenu, source, sourceId, rawImages, hiddenPages, state.currentPage, setPage, router, onHideImage])

  const handleToggleFavorite = useCallback(async () => {
    if (!imageMenu) return
    const img = rawImages.find(i => i.page_num === imageMenu.pageNum)
    if (!img?.id) return

    const isFav = favImageIds.has(img.id)
    setImageMenu(null) // close menu first

    try {
      if (isFav) {
        await api.library.unfavoriteImage(img.id)
        setFavImageIds(prev => { const next = new Set(prev); next.delete(img.id); return next })
        toast.success(t('reader.imageUnfavorited'))
      } else {
        await api.library.favoriteImage(img.id)
        setFavImageIds(prev => new Set(prev).add(img.id))
        toast.success(t('reader.imageFavorited'))
      }
    } catch {
      toast.error(t('reader.favoriteFailed'))
    }
  }, [imageMenu, rawImages, favImageIds])

  const handleAutoAdvanceToggle = useCallback(() => {
    const next = !autoAdvanceEnabled
    setAutoAdvanceEnabled(next)
    saveReaderSettings({ autoAdvanceEnabled: next })
  }, [autoAdvanceEnabled])

  const handleAutoAdvanceInterval = useCallback((s: number) => {
    setAutoAdvanceSeconds(s)
    saveReaderSettings({ autoAdvanceSeconds: s })
  }, [])

  const currentImage = images.find((i) => i.pageNum === state.currentPage)
  const nextImage = images.find((i) => i.pageNum === state.currentPage + 1) ?? null

  // When downloading progressively, the current page may not have been imported yet.
  const isDownloading = downloadStatus === 'downloading'
  const pageNotReady = !currentImage && isDownloading && images.length > 0

  // Compute favorite eligibility for current context menu image
  const contextMenuImg = imageMenu ? rawImages.find(i => i.page_num === imageMenu.pageNum) : undefined
  const canFavoriteContextImg = !isProxyMode && contextMenuImg?.id != null && contextMenuImg?.file_path != null

  return (
    <div ref={containerRef} className="reader-container flex flex-col bg-black">
      {/* Top overlay — always rendered, slides in/out */}
      <div
        className={`absolute top-0 left-0 right-0 z-20 transition-transform duration-300 ${
          state.showOverlay ? 'translate-y-0' : '-translate-y-full'
        } ${!state.showOverlay ? 'pointer-events-none' : ''}`}
      >
        <ReaderOverlay
          currentPage={state.currentPage}
          totalPages={effectiveTotalPages}
          viewMode={state.viewMode}
          scaleMode={state.scaleMode}
          readingDirection={state.readingDirection}
          autoAdvanceEnabled={autoAdvanceEnabled}
          autoAdvanceSeconds={autoAdvanceSeconds}
          onBack={handleBack}
          onViewModeChange={setViewMode}
          onScaleModeChange={setScaleMode}
          onReadingDirectionChange={setReadingDirection}
          onAutoAdvanceToggle={handleAutoAdvanceToggle}
          onAutoAdvanceIntervalChange={handleAutoAdvanceInterval}
          onShowHelp={handleShowHelp}
          onPageSelect={setPageWithPrefetch}
        />
      </div>

      {/* Main content — absolute inset-0 gives children a definite height so h-full resolves
          correctly on iOS Safari even during CSS transitions on sibling overlay elements. */}
      <div className="absolute inset-0 overflow-hidden">
        {state.viewMode === 'single' && currentImage && (
          <SinglePageView
            image={currentImage}
            isLoading={pageLoading}
            onNext={rawNextPage}
            onPrev={rawPrevPage}
            onToggleOverlay={handleToggleOverlay}
            onImageLoaded={handleImageLoaded}
            scaleMode={state.scaleMode}
            readingDirection={state.readingDirection}
            showOverlay={state.showOverlay}
            currentPage={state.currentPage}
            onZoomChange={handleZoomChange}
            imageLongPress={makeSinglePageHandlers(currentImage)}
          />
        )}

        {state.viewMode === 'webtoon' && (
          <WebtoonView
            images={images}
            onPageChange={setPageWithPrefetch}
            onToggleOverlay={handleToggleOverlay}
            scrollToPage={state.currentPage}
            scaleMode={state.scaleMode}
            imageLongPress={makePerImageHandlers}
          />
        )}

        {state.viewMode === 'double' && currentImage && (
          <DoublePageView
            leftImage={currentImage}
            rightImage={nextImage}
            isLoading={pageLoading}
            onNext={() => setPageWithPrefetch(state.currentPage + 2)}
            onPrev={() => setPageWithPrefetch(state.currentPage - 2)}
            onToggleOverlay={handleToggleOverlay}
            onImageLoaded={handleImageLoaded}
            scaleMode={state.scaleMode}
            readingDirection={state.readingDirection}
            showOverlay={state.showOverlay}
            currentPage={state.currentPage}
            onZoomChange={handleZoomChange}
            imageLongPress={makePerImageHandlers}
          />
        )}

        {/* Downloading: current page not yet imported — show spinner instead of black screen */}
        {pageNotReady && (
          <div className="flex h-full w-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
              <p className="text-sm text-white/50">{t('reader.pageNotReady')}</p>
            </div>
          </div>
        )}
      </div>

      {/* Bottom thumbnail strip — always rendered, slides in/out */}
      <div
        className={`absolute bottom-0 left-0 right-0 z-20 transition-transform duration-300 ${
          state.showOverlay ? 'translate-y-0' : 'translate-y-full'
        } ${!state.showOverlay ? 'pointer-events-none' : ''}`}
      >
        <ThumbnailStrip
          images={images}
          currentPage={state.currentPage}
          onPageSelect={setPageWithPrefetch}
          previews={previews}
          onScrollToPage={onSeekToPage}
          isVisible={state.showOverlay}
          readingDirection={state.readingDirection}
        />
      </div>

      {/* Status bar — hidden via opacity when overlay is shown to avoid bleed-through the thumbnail strip */}
      <div
        className={`absolute left-0 right-0 bottom-0 z-10 transition-opacity duration-300 ${state.showOverlay ? 'opacity-0' : 'opacity-100'}`}
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <StatusBar
          currentPage={state.currentPage}
          totalPages={effectiveTotalPages}
          settings={readerSettings}
          countdown={countdown}
          autoAdvanceEnabled={autoAdvanceEnabled}
          onPageSelect={setPageWithPrefetch}
          readingDirection={state.readingDirection}
        />
      </div>

      {/* Help overlay */}
      {showHelp && (
        <HelpOverlay readingDirection={state.readingDirection} viewMode={state.viewMode} onDismiss={handleDismissHelp} />
      )}

      {/* Image context menu (long-press / right-click) */}
      {imageMenu?.open && (
        <ImageContextMenu
          open={true}
          onClose={() => setImageMenu(null)}
          position={imageMenu.position}
          imageUrl={imageMenu.imageUrl}
          imageName={imageMenu.imageName}
          onHide={
            (imageMenu.pageNum && images.find(i => i.pageNum === imageMenu.pageNum)?.isLocal) || onHideImage
              ? handleHideImage
              : undefined
          }
          isFavorited={canFavoriteContextImg ? favImageIds.has(contextMenuImg!.id) : undefined}
          onToggleFavorite={canFavoriteContextImg ? handleToggleFavorite : undefined}
        />
      )}
    </div>
  )
}
