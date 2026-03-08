'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { X } from 'lucide-react'
import type { GalleryImage } from '@/lib/types'
import type { ReaderImage, ViewMode, ScaleMode, ReadingDirection, ReaderSettings } from './types'
import { DEFAULT_READER_SETTINGS } from './types'
import { t } from '@/lib/i18n'
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

// ── URL resolver ──────────────────────────────────────────────────────

function resolveImageUrl(image: GalleryImage, sourceId: string): string {
  if (image.file_path != null) {
    return image.file_path.replace('/data/', '/media/')
  }
  return `/api/eh/image-proxy/${sourceId}/${image.page_num}`
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
}: {
  image: ReaderImage
  className?: string
  style?: React.CSSProperties
  draggable?: boolean
  loading?: 'lazy' | 'eager'
  dataPage?: number
  innerRef?: React.Ref<HTMLImageElement | HTMLVideoElement>
  onLoad?: () => void
}) {
  if (image.mediaType === 'video') {
    return (
      <video
        ref={innerRef as React.Ref<HTMLVideoElement>}
        src={image.url}
        className={className}
        style={style}
        data-page={dataPage}
        autoPlay
        loop
        muted
        playsInline
        controls
        onLoadedData={onLoad}
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
  galleryId: number
  sourceId: string
  downloadStatus: 'proxy_only' | 'partial' | 'complete'
  images: GalleryImage[]
  totalPages: number
  initialPage?: number
  /** EH preview thumbnail map: { "1": "url" or "url|ox|w|h" } */
  previews?: Record<string, string>
}

// ── SinglePageView ────────────────────────────────────────────────────

interface SinglePageViewProps {
  image: ReaderImage
  isLoading: boolean
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
  onImageLoaded: () => void
  scaleMode: ScaleMode
  readingDirection: ReadingDirection
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
}: SinglePageViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { isZoomed, transform } = usePinchZoom(containerRef as React.RefObject<HTMLElement | null>)

  const leftAction = readingDirection === 'rtl' ? onNext : onPrev
  const rightAction = readingDirection === 'rtl' ? onPrev : onNext

  return (
    <div ref={containerRef} className={`${getScaleContainerClass(scaleMode)} h-full w-full`}>
      <div
        style={{ transform, transformOrigin: 'center center', transition: 'transform 0.05s linear' }}
        className="w-full h-full flex items-center justify-center"
      >
        <MediaElement
          image={image}
          className={getScaleImageClass(scaleMode)}
          draggable={false}
          onLoad={onImageLoaded}
        />
      </div>
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none">
          <Spinner />
        </div>
      )}
      {!isZoomed && readingDirection === 'vertical' ? (
        <>
          <div
            className="reader-tap-zone absolute top-0 left-0 w-full h-[30%] cursor-pointer select-none"
            onClick={onPrev}
            aria-label="Previous page"
          />
          <div
            className="reader-tap-zone absolute top-[30%] left-0 w-full h-[40%] cursor-pointer select-none"
            onClick={onToggleOverlay}
            aria-label="Toggle controls"
          />
          <div
            className="reader-tap-zone absolute bottom-0 left-0 w-full h-[30%] cursor-pointer select-none"
            onClick={onNext}
            aria-label="Next page"
          />
        </>
      ) : !isZoomed ? (
        <>
          <div
            className="reader-tap-zone absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
            onClick={leftAction}
            aria-label={readingDirection === 'rtl' ? 'Next page' : 'Previous page'}
          />
          <div
            className="reader-tap-zone absolute left-[30%] top-0 h-full w-[40%] cursor-pointer select-none"
            onClick={onToggleOverlay}
            aria-label="Toggle controls"
          />
          <div
            className="reader-tap-zone absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
            onClick={rightAction}
            aria-label={readingDirection === 'rtl' ? 'Previous page' : 'Next page'}
          />
        </>
      ) : null}
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
}

function WebtoonView({ images, onPageChange, onToggleOverlay, scrollToPage }: WebtoonViewProps) {
  const elRefs = useRef<Map<number, HTMLElement>>(new Map())
  const scrollRef = useRef<HTMLDivElement>(null)
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set())
  const lastPage = images.length > 0 ? images[images.length - 1].pageNum : 0
  // Tracks the last page number reported by the IntersectionObserver (i.e. from scrolling).
  const lastReportedPage = useRef<number>(0)

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return

    // Clean stale refs for pages no longer in the image list
    const validPages = new Set(images.map((img) => img.pageNum))
    elRefs.current.forEach((_, key) => {
      if (!validPages.has(key)) elRefs.current.delete(key)
    })

    const observer = new IntersectionObserver(
      (entries) => {
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
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  }, [scrollToPage])

  const handleImageLoaded = useCallback((pageNum: number) => {
    setLoadedPages((prev) => new Set([...prev, pageNum]))
  }, [])

  // Show spinner if the last visible image hasn't loaded yet
  const showBottomSpinner = lastPage > 0 && !loadedPages.has(lastPage)

  return (
    <div ref={scrollRef} className="reader-webtoon-scroll flex flex-col items-center w-full h-full">
      {images.map((img) => (
        <MediaElement
          key={img.pageNum}
          innerRef={(el: HTMLImageElement | HTMLVideoElement | null) => {
            if (el) elRefs.current.set(img.pageNum, el)
            else elRefs.current.delete(img.pageNum)
          }}
          image={img}
          className="w-full block"
          dataPage={img.pageNum}
          onLoad={() => handleImageLoaded(img.pageNum)}
        />
      ))}
      {showBottomSpinner && (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      )}
      {/* Tap zone for overlay toggle in webtoon mode */}
      <button
        type="button"
        className="fixed top-1/3 left-1/4 w-1/2 h-1/3 z-10 cursor-pointer bg-transparent border-none p-0"
        onClick={onToggleOverlay}
        aria-label="Toggle controls"
        tabIndex={0}
      />
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
}: DoublePageViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { isZoomed, transform } = usePinchZoom(containerRef as React.RefObject<HTMLElement | null>)

  const leftAction = readingDirection === 'rtl' ? onNext : onPrev
  const rightAction = readingDirection === 'rtl' ? onPrev : onNext

  // RTL: swap display order
  const firstImage = readingDirection === 'rtl' ? rightImage : leftImage
  const secondImage = readingDirection === 'rtl' ? leftImage : rightImage

  const imgClass = getScaleImageClass(scaleMode === 'fit-both' ? 'fit-both' : scaleMode)

  return (
    <div ref={containerRef} className="relative flex h-full w-full items-center justify-center overflow-hidden">
      <div
        style={{ transform, transformOrigin: 'center center', transition: 'transform 0.05s linear' }}
        className="flex h-full w-full flex-row"
      >
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          {firstImage ? (
            <MediaElement
              image={firstImage}
              className={imgClass}
              draggable={false}
              onLoad={onImageLoaded}
            />
          ) : (
            <div className="h-full w-full" />
          )}
        </div>
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          {secondImage ? (
            <MediaElement
              image={secondImage}
              className={imgClass}
              draggable={false}
              onLoad={onImageLoaded}
            />
          ) : (
            <div className="h-full w-full" />
          )}
        </div>
      </div>
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none">
          <Spinner />
        </div>
      )}
      {!isZoomed && readingDirection === 'vertical' ? (
        <>
          <div
            className="reader-tap-zone absolute top-0 left-0 w-full h-[30%] cursor-pointer select-none"
            onClick={onPrev}
            aria-label="Previous page"
          />
          <div
            className="reader-tap-zone absolute top-[30%] left-0 w-full h-[40%] cursor-pointer select-none"
            onClick={onToggleOverlay}
            aria-label="Toggle controls"
          />
          <div
            className="reader-tap-zone absolute bottom-0 left-0 w-full h-[30%] cursor-pointer select-none"
            onClick={onNext}
            aria-label="Next page"
          />
        </>
      ) : !isZoomed ? (
        <>
          <div
            className="reader-tap-zone absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
            onClick={leftAction}
            aria-label={readingDirection === 'rtl' ? 'Next page' : 'Previous page'}
          />
          <div
            className="reader-tap-zone absolute left-[30%] top-0 h-full w-[40%] cursor-pointer select-none"
            onClick={onToggleOverlay}
            aria-label="Toggle controls"
          />
          <div
            className="reader-tap-zone absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
            onClick={rightAction}
            aria-label={readingDirection === 'rtl' ? 'Previous page' : 'Next page'}
          />
        </>
      ) : null}
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
}: ReaderOverlayProps) {
  const VIEW_MODES: { mode: ViewMode; label: string }[] = [
    { mode: 'single', label: t('reader.viewModeSingle') },
    { mode: 'webtoon', label: t('reader.viewModeWebtoon') },
    { mode: 'double', label: t('reader.viewModeDouble') },
  ]

  const SCALE_MODES: { mode: ScaleMode; label: string }[] = [
    { mode: 'fit-both', label: t('reader.scaleFitBoth') },
    { mode: 'fit-width', label: t('reader.scaleFitWidth') },
    { mode: 'fit-height', label: t('reader.scaleFitHeight') },
    { mode: 'original', label: t('reader.scaleOriginal') },
  ]

  const DIRECTIONS: { dir: ReadingDirection; label: string }[] = [
    { dir: 'ltr', label: t('reader.dirLtr') },
    { dir: 'rtl', label: t('reader.dirRtl') },
    { dir: 'vertical', label: t('reader.dirVertical') },
  ]

  const btnActive = 'bg-white text-black'
  const btnInactive = 'bg-white/10 hover:bg-white/20 text-white'

  return (
    <div
      className="absolute top-0 left-0 right-0 z-20 bg-black/70 text-white text-sm backdrop-blur-sm"
      style={{ paddingTop: 'env(safe-area-inset-top)' }}
    >
      {/* Row 1: page indicator (left) + help + close (right) */}
      <div className="flex items-center gap-2 px-4 py-2">
        <span className="font-mono tabular-nums whitespace-nowrap text-xs">
          {currentPage} / {totalPages}
        </span>

        <div className="flex-1" />

        <button
          onClick={onShowHelp}
          className="rounded bg-white/10 px-2 py-1 text-[11px] hover:bg-white/20 shrink-0"
          title={t('reader.helpButton')}
        >
          ?
        </button>

        <button
          onClick={onBack}
          className="rounded bg-white/10 p-1.5 hover:bg-white/20 shrink-0"
          title="Go back"
        >
          <X size={14} />
        </button>
      </div>

      {/* Row 2: scrollable controls — view / scale / direction */}
      <div
        className="flex items-center gap-3 px-4 pb-2 border-t border-white/10 pt-2 overflow-x-auto"
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
      >
        {/* View mode group */}
        <div className="flex gap-0.5 shrink-0">
          {VIEW_MODES.map(({ mode, label }) => (
            <button
              key={mode}
              onClick={() => onViewModeChange(mode)}
              className={`rounded px-2 py-1 text-[11px] font-medium transition-colors whitespace-nowrap ${viewMode === mode ? btnActive : btnInactive}`}
              title={label}
            >
              {label}
            </button>
          ))}
        </div>

        <span className="text-white/30 shrink-0 select-none">|</span>

        {/* Scale mode group */}
        <div className="flex gap-0.5 shrink-0">
          {SCALE_MODES.map(({ mode, label }) => (
            <button
              key={mode}
              onClick={() => onScaleModeChange(mode)}
              className={`rounded px-2 py-1 text-[11px] font-medium transition-colors whitespace-nowrap ${scaleMode === mode ? btnActive : btnInactive}`}
              title={label}
            >
              {label}
            </button>
          ))}
        </div>

        <span className="text-white/30 shrink-0 select-none">|</span>

        {/* Direction group */}
        <div className="flex gap-0.5 shrink-0">
          {DIRECTIONS.map(({ dir, label }) => (
            <button
              key={dir}
              onClick={() => onReadingDirectionChange(dir)}
              className={`rounded px-2 py-1 text-[11px] font-medium transition-colors whitespace-nowrap ${readingDirection === dir ? btnActive : btnInactive}`}
              title={label}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Row 3: Auto advance controls */}
      <div className="flex items-center gap-3 px-4 pb-2 border-t border-white/10 pt-2">
        <span className="text-[11px] text-white/60 shrink-0">{t('reader.autoAdvance')}</span>
        <button
          onClick={onAutoAdvanceToggle}
          className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${autoAdvanceEnabled ? 'bg-vault-accent' : 'bg-white/20'}`}
          aria-label={t('reader.autoAdvance')}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${autoAdvanceEnabled ? 'translate-x-4' : ''}`}
          />
        </button>
        {autoAdvanceEnabled && (
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={2}
              max={30}
              step={1}
              value={autoAdvanceSeconds}
              onChange={(e) => onAutoAdvanceIntervalChange(Number(e.target.value))}
              className="w-24 accent-white"
            />
            <span className="text-[11px] tabular-nums whitespace-nowrap">{autoAdvanceSeconds}s</span>
          </div>
        )}
      </div>
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
}

function ThumbnailStrip({ images, currentPage, onPageSelect, previews }: ThumbnailStripProps) {
  const activeRef = useRef<HTMLButtonElement | null>(null)
  const stripRef = useRef<HTMLDivElement | null>(null)
  const userScrollingRef = useRef(false)
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    const el = stripRef.current
    if (!el) return
    const onScroll = () => {
      userScrollingRef.current = true
      clearTimeout(scrollTimerRef.current)
      scrollTimerRef.current = setTimeout(() => {
        userScrollingRef.current = false
      }, 1500)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      el.removeEventListener('scroll', onScroll)
      clearTimeout(scrollTimerRef.current)
    }
  }, [])

  useEffect(() => {
    if (!userScrollingRef.current) {
      activeRef.current?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
    }
  }, [currentPage])

  return (
    <div
      ref={stripRef}
      className="reader-thumb-strip absolute bottom-0 left-0 right-0 z-20 flex gap-1 bg-black/70 px-2 py-2 backdrop-blur-sm"
    >
      {images.map((img) => {
        const isActive = img.pageNum === currentPage
        const previewRaw = previews?.[String(img.pageNum)]

        let thumbSrc: string | null = null
        let spriteStyle: React.CSSProperties | null = null

        if (previewRaw) {
          if (previewRaw.includes('|')) {
            const [spriteUrl, ox] = previewRaw.split('|')
            spriteStyle = {
              backgroundImage: `url(/api/eh/thumb-proxy?url=${encodeURIComponent(spriteUrl)})`,
              backgroundPosition: `${ox}px 0`,
              backgroundSize: 'auto 100%',
              backgroundRepeat: 'no-repeat',
              width: '100%',
              height: '100%',
            }
          } else {
            thumbSrc = `/api/eh/thumb-proxy?url=${encodeURIComponent(previewRaw)}`
          }
        } else if (img.isLocal) {
          thumbSrc = img.url
        }

        return (
          <button
            key={img.pageNum}
            ref={isActive ? activeRef : null}
            onClick={() => onPageSelect(img.pageNum)}
            className={`relative flex-shrink-0 overflow-hidden rounded transition-all ${
              isActive ? 'ring-2 ring-white opacity-100' : 'opacity-50 hover:opacity-80'
            }`}
            style={{ width: 48, height: 64 }}
            title={`Page ${img.pageNum}`}
          >
            {spriteStyle ? (
              <div style={spriteStyle} />
            ) : thumbSrc ? (
              <img
                src={thumbSrc}
                alt={`Thumb ${img.pageNum}`}
                className="h-full w-full object-cover"
                loading="lazy"
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
  )
}

// ── StatusBar ─────────────────────────────────────────────────────────

interface StatusBarProps {
  currentPage: number
  totalPages: number
  settings: ReaderSettings
  countdown: number
  autoAdvanceEnabled: boolean
}

function StatusBar({ currentPage, totalPages, settings, countdown, autoAdvanceEnabled }: StatusBarProps) {
  const clock = useStatusBarClock(settings.statusBarEnabled && settings.statusBarShowClock)

  if (!settings.statusBarEnabled) return null

  const progress = totalPages > 0 ? (currentPage / totalPages) * 100 : 0

  return (
    <div
      className="reader-status-bar absolute bottom-0 left-0 right-0 z-10 flex items-center gap-3 px-3"
      style={{ height: 24, background: 'rgba(0,0,0,0.55)' }}
    >
      {settings.statusBarShowClock && clock && (
        <span className="text-[11px] text-white/80 tabular-nums shrink-0">{clock}</span>
      )}

      {settings.statusBarShowProgress && (
        <div className="flex-1 h-1.5 bg-white/20 rounded-full overflow-hidden">
          <div
            className="h-full bg-white/70 rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
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
  onDismiss: () => void
}

function HelpOverlay({ readingDirection, onDismiss }: HelpOverlayProps) {
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
    <div
      className="absolute inset-0 z-50 flex flex-col"
      onClick={onDismiss}
    >
      {isVertical ? (
        /* Vertical mode: top/middle/bottom zones */
        <div className="flex flex-col flex-1">
          {/* Top zone — previous page */}
          <div className="h-[30%] w-full flex items-center justify-center bg-blue-500/20 border-b border-blue-400/30">
            <div className="text-white text-sm font-medium">{t('reader.helpTapLeft')}</div>
          </div>
          {/* Middle zone — toggle controls */}
          <div className="flex-1 w-full flex items-center justify-center bg-white/5 border-b border-white/10">
            <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
          </div>
          {/* Bottom zone — next page */}
          <div className="h-[30%] w-full flex items-center justify-center bg-green-500/20">
            <div className="text-white text-sm font-medium">{t('reader.helpTapRight')}</div>
          </div>
        </div>
      ) : (
        /* Horizontal mode: left/center/right zones */
        <div className="flex flex-1">
          {/* Left zone */}
          <div className="w-[30%] h-full flex items-center justify-center bg-blue-500/20 border-r border-blue-400/30">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{leftLabel}</div>
            </div>
          </div>
          {/* Center zone */}
          <div className="flex-1 h-full flex items-center justify-center bg-white/5 border-r border-white/10">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
            </div>
          </div>
          {/* Right zone */}
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
          <p className="text-white text-sm">{t('reader.helpSwipe')}</p>
          <p className="text-white/60 text-xs">{t('reader.helpKeyboard')}</p>
          <p className="text-white/40 text-xs">{t('reader.helpDismiss')}</p>
        </div>
      </div>
    </div>
  )
}

// ── Reader (main component) ───────────────────────────────────────────

export default function Reader({
  galleryId,
  sourceId,
  downloadStatus,
  images: rawImages,
  totalPages,
  initialPage = 1,
  previews,
}: ReaderProps) {
  const router = useRouter()
  const isProxyMode = downloadStatus !== 'complete'

  const images: ReaderImage[] = rawImages.map((img) => ({
    pageNum: img.page_num,
    url: resolveImageUrl(img, sourceId),
    isLocal: img.file_path != null,
    width: img.width ?? undefined,
    height: img.height ?? undefined,
    mediaType: img.media_type,
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
  } = useReaderState(initialPage, totalPages, galleryId)

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

  const isLastPage = state.currentPage >= totalPages

  const { countdown, resetCountdown } = useAutoAdvance(
    autoAdvanceEnabled,
    autoAdvanceSeconds,
    rawNextPage,
    isLastPage,
    state.showOverlay,
  )

  // Reset countdown on manual page change
  useEffect(() => {
    resetCountdown()
  }, [state.currentPage, resetCountdown])

  const containerRef = useRef<HTMLDivElement>(null)

  // Track image loading state for single/double page views
  const [pageLoading, setPageLoading] = useState(false)
  const loadingPageRef = useRef(state.currentPage)
  const loadingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // When page changes, start a short timer before showing the spinner.
  // If the image loads before the timer fires, the spinner never appears.
  useEffect(() => {
    if (state.viewMode !== 'webtoon' && state.currentPage !== loadingPageRef.current) {
      loadingPageRef.current = state.currentPage
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

  const handleImageLoaded = useCallback(() => {
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current)
      loadingTimerRef.current = null
    }
    setPageLoading(false)
  }, [])

  useSequentialPrefetch(images, state.currentPage, isProxyMode)
  useProgressSave(galleryId, state.currentPage)

  // Swipe: respect RTL direction
  const swipeLeft = useCallback(() => {
    if (state.readingDirection === 'rtl') rawPrevPage()
    else rawNextPage()
  }, [state.readingDirection, rawNextPage, rawPrevPage])

  const swipeRight = useCallback(() => {
    if (state.readingDirection === 'rtl') rawNextPage()
    else rawPrevPage()
  }, [state.readingDirection, rawNextPage, rawPrevPage])

  useTouchGesture(containerRef as React.RefObject<HTMLElement | null>, swipeLeft, swipeRight)

  useKeyboardNav(rawNextPage, rawPrevPage, state.readingDirection)

  // Escape key to go back
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') router.back()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [router])

  const handleToggleOverlay = useCallback(() => toggleOverlay(), [toggleOverlay])
  const handleBack = useCallback(() => router.back(), [router])

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

  // Offset for status bar (don't overlap thumbnail strip or overlay)
  const statusBarBottomOffset = state.showOverlay ? 80 : 0

  return (
    <div ref={containerRef} className="reader-container relative flex flex-col bg-black">
      {/* Top overlay */}
      {state.showOverlay && (
        <ReaderOverlay
          currentPage={state.currentPage}
          totalPages={totalPages}
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
        />
      )}

      {/* Main content */}
      <div className="flex-1 overflow-hidden">
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
          />
        )}

        {state.viewMode === 'webtoon' && (
          <WebtoonView
            images={images}
            onPageChange={setPage}
            onToggleOverlay={handleToggleOverlay}
            scrollToPage={state.currentPage}
          />
        )}

        {state.viewMode === 'double' && currentImage && (
          <DoublePageView
            leftImage={currentImage}
            rightImage={nextImage}
            isLoading={pageLoading}
            onNext={() => setPage(state.currentPage + 2)}
            onPrev={() => setPage(state.currentPage - 2)}
            onToggleOverlay={handleToggleOverlay}
            onImageLoaded={handleImageLoaded}
            scaleMode={state.scaleMode}
            readingDirection={state.readingDirection}
          />
        )}
      </div>

      {/* Bottom thumbnail strip (shown with overlay) */}
      {state.showOverlay && (
        <ThumbnailStrip
          images={images}
          currentPage={state.currentPage}
          onPageSelect={setPage}
          previews={previews}
        />
      )}

      {/* Status bar (always visible unless disabled, offset when overlay+strip shown) */}
      {!state.showOverlay && (
        <div
          className="absolute left-0 right-0 z-10"
          style={{ bottom: statusBarBottomOffset }}
        >
          <StatusBar
            currentPage={state.currentPage}
            totalPages={totalPages}
            settings={readerSettings}
            countdown={countdown}
            autoAdvanceEnabled={autoAdvanceEnabled}
          />
        </div>
      )}

      {/* Help overlay */}
      {showHelp && (
        <HelpOverlay
          readingDirection={state.readingDirection}
          onDismiss={handleDismissHelp}
        />
      )}
    </div>
  )
}
