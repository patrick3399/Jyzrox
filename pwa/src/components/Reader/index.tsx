'use client'
import { useCallback, useEffect, useRef } from 'react'
import type { GalleryImage } from '@/lib/types'
import type { ReaderImage, ViewMode } from './types'
import {
  useReaderState,
  useSequentialPrefetch,
  useTouchGesture,
  useKeyboardNav,
  useProgressSave,
  useFullscreen,
} from './hooks'

// ── URL resolver ──────────────────────────────────────────────────────

function resolveImageUrl(image: GalleryImage, sourceId: string): string {
  if (image.file_path != null) {
    // /data/gallery/... → /media/gallery/...
    return image.file_path.replace('/data/', '/media/')
  }
  return `/api/eh/image-proxy/${sourceId}/${image.page_num}`
}

// ── Props ─────────────────────────────────────────────────────────────

interface ReaderProps {
  galleryId: number
  sourceId: string
  downloadStatus: 'proxy_only' | 'partial' | 'complete'
  images: GalleryImage[]
  totalPages: number
  initialPage?: number
}

// ── Sub-components ────────────────────────────────────────────────────

interface SinglePageViewProps {
  image: ReaderImage
  brightness: number
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
}

function SinglePageView({ image, brightness, onNext, onPrev, onToggleOverlay }: SinglePageViewProps) {
  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden">
      <img
        src={image.url}
        alt={`Page ${image.pageNum}`}
        className="max-h-full max-w-full object-contain"
        style={{ filter: `brightness(${brightness})` }}
        draggable={false}
      />

      {/* Left 30% – prev page */}
      <div
        className="absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
        onClick={onPrev}
        aria-label="Previous page"
      />

      {/* Middle 40% – toggle overlay */}
      <div
        className="absolute left-[30%] top-0 h-full w-[40%] cursor-pointer select-none"
        onClick={onToggleOverlay}
        aria-label="Toggle controls"
      />

      {/* Right 30% – next page */}
      <div
        className="absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
        onClick={onNext}
        aria-label="Next page"
      />
    </div>
  )
}

interface WebtoonViewProps {
  images: ReaderImage[]
  brightness: number
  onPageChange: (page: number) => void
}

function WebtoonView({ images, brightness, onPageChange }: WebtoonViewProps) {
  const imgRefs = useRef<Map<number, HTMLImageElement>>(new Map())

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the topmost visible entry
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
          if (!isNaN(pageNum)) onPageChange(pageNum)
        }
      },
      { threshold: 0.5 }
    )

    imgRefs.current.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [images, onPageChange])

  return (
    <div className="flex flex-col items-center w-full overflow-y-auto">
      {images.map((img) => (
        <img
          key={img.pageNum}
          ref={(el) => {
            if (el) imgRefs.current.set(img.pageNum, el)
            else imgRefs.current.delete(img.pageNum)
          }}
          src={img.url}
          alt={`Page ${img.pageNum}`}
          data-page={img.pageNum}
          className="w-full block"
          style={{ filter: `brightness(${brightness})` }}
          draggable={false}
        />
      ))}
    </div>
  )
}

interface DoublePageViewProps {
  leftImage: ReaderImage
  rightImage: ReaderImage | null
  brightness: number
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
}

function DoublePageView({
  leftImage,
  rightImage,
  brightness,
  onNext,
  onPrev,
  onToggleOverlay,
}: DoublePageViewProps) {
  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden">
      <div className="flex h-full w-full flex-row">
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          <img
            src={leftImage.url}
            alt={`Page ${leftImage.pageNum}`}
            className="max-h-full max-w-full object-contain"
            style={{ filter: `brightness(${brightness})` }}
            draggable={false}
          />
        </div>
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          {rightImage ? (
            <img
              src={rightImage.url}
              alt={`Page ${rightImage.pageNum}`}
              className="max-h-full max-w-full object-contain"
              style={{ filter: `brightness(${brightness})` }}
              draggable={false}
            />
          ) : (
            <div className="h-full w-full" />
          )}
        </div>
      </div>

      {/* Left 30% – prev */}
      <div
        className="absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
        onClick={onPrev}
        aria-label="Previous page"
      />

      {/* Middle 40% – toggle overlay */}
      <div
        className="absolute left-[30%] top-0 h-full w-[40%] cursor-pointer select-none"
        onClick={onToggleOverlay}
        aria-label="Toggle controls"
      />

      {/* Right 30% – next */}
      <div
        className="absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
        onClick={onNext}
        aria-label="Next page"
      />
    </div>
  )
}

interface ReaderOverlayProps {
  currentPage: number
  totalPages: number
  viewMode: ViewMode
  brightness: number
  isFullscreen: boolean
  bgColor: string
  onViewModeChange: (mode: ViewMode) => void
  onBrightnessChange: (v: number) => void
  onBgColorChange: (c: string) => void
  onToggleFullscreen: () => void
}

function ReaderOverlay({
  currentPage,
  totalPages,
  viewMode,
  brightness,
  isFullscreen,
  bgColor,
  onViewModeChange,
  onBrightnessChange,
  onBgColorChange,
  onToggleFullscreen,
}: ReaderOverlayProps) {
  const VIEW_MODES: ViewMode[] = ['single', 'webtoon', 'double']

  return (
    <div className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between gap-3 bg-black/70 px-4 py-3 text-white text-sm backdrop-blur-sm">
      {/* Page indicator */}
      <span className="font-mono tabular-nums whitespace-nowrap">
        {currentPage} / {totalPages}
      </span>

      {/* View mode buttons */}
      <div className="flex gap-1">
        {VIEW_MODES.map((m) => (
          <button
            key={m}
            onClick={() => onViewModeChange(m)}
            className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
              viewMode === m
                ? 'bg-white text-black'
                : 'bg-white/10 hover:bg-white/20 text-white'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Brightness slider */}
      <div className="flex items-center gap-2">
        <span className="text-xs opacity-70">brightness</span>
        <input
          type="range"
          min={0.3}
          max={1.0}
          step={0.05}
          value={brightness}
          onChange={(e) => onBrightnessChange(Number(e.target.value))}
          className="w-24 accent-white"
        />
      </div>

      {/* Background colour picker */}
      <div className="flex items-center gap-1">
        <span className="text-xs opacity-70">bg</span>
        <input
          type="color"
          value={bgColor}
          onChange={(e) => onBgColorChange(e.target.value)}
          className="h-6 w-6 cursor-pointer rounded border-0 bg-transparent p-0"
        />
      </div>

      {/* Fullscreen toggle */}
      <button
        onClick={onToggleFullscreen}
        className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/20"
        title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
      >
        {isFullscreen ? '⤓' : '⤢'}
      </button>
    </div>
  )
}

interface ThumbnailStripProps {
  images: ReaderImage[]
  currentPage: number
  onPageSelect: (page: number) => void
}

function ThumbnailStrip({ images, currentPage, onPageSelect }: ThumbnailStripProps) {
  const activeRef = useRef<HTMLButtonElement | null>(null)

  // Scroll active thumbnail into view whenever currentPage changes
  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }, [currentPage])

  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 flex gap-1 overflow-x-auto bg-black/70 px-2 py-2 backdrop-blur-sm">
      {images.map((img) => {
        const isActive = img.pageNum === currentPage
        return (
          <button
            key={img.pageNum}
            ref={isActive ? activeRef : null}
            onClick={() => onPageSelect(img.pageNum)}
            className={`relative flex-shrink-0 overflow-hidden rounded transition-all ${
              isActive
                ? 'ring-2 ring-white opacity-100'
                : 'opacity-50 hover:opacity-80'
            }`}
            style={{ width: 48, height: 64 }}
            title={`Page ${img.pageNum}`}
          >
            <img
              src={img.url}
              alt={`Thumb ${img.pageNum}`}
              className="h-full w-full object-cover"
              loading="lazy"
            />
            <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-center text-[10px] text-white leading-tight py-px">
              {img.pageNum}
            </span>
          </button>
        )
      })}
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
}: ReaderProps) {
  const isProxyMode = downloadStatus !== 'complete'

  // Resolve URLs once
  const images: ReaderImage[] = rawImages.map((img) => ({
    pageNum: img.page_num,
    url: resolveImageUrl(img, sourceId),
    isLocal: img.file_path != null,
    width: img.width ?? undefined,
    height: img.height ?? undefined,
  }))

  const {
    state,
    setPage,
    nextPage,
    prevPage,
    setViewMode,
    setBrightness,
    setBgColor,
    toggleOverlay,
  } = useReaderState(initialPage, totalPages)

  const containerRef = useRef<HTMLDivElement>(null)
  const { isFullscreen, toggle: toggleFullscreen } = useFullscreen(
    containerRef as React.RefObject<HTMLElement | null>
  )

  useSequentialPrefetch(images, state.currentPage, isProxyMode)
  useProgressSave(galleryId, state.currentPage)

  useTouchGesture(
    containerRef as React.RefObject<HTMLElement | null>,
    nextPage,
    prevPage
  )

  useKeyboardNav(nextPage, prevPage, toggleFullscreen)

  const handleToggleOverlay = useCallback(() => toggleOverlay(), [toggleOverlay])

  const currentImage = images.find((i) => i.pageNum === state.currentPage)
  const nextImage = images.find((i) => i.pageNum === state.currentPage + 1) ?? null

  return (
    <div
      ref={containerRef}
      className={`relative flex h-screen w-full flex-col overflow-hidden ${
        isFullscreen ? 'fixed inset-0 z-50' : ''
      }`}
      style={{ background: state.bgColor }}
    >
      {/* Top overlay */}
      {state.showOverlay && (
        <ReaderOverlay
          currentPage={state.currentPage}
          totalPages={totalPages}
          viewMode={state.viewMode}
          brightness={state.brightness}
          isFullscreen={isFullscreen}
          bgColor={state.bgColor}
          onViewModeChange={setViewMode}
          onBrightnessChange={setBrightness}
          onBgColorChange={setBgColor}
          onToggleFullscreen={toggleFullscreen}
        />
      )}

      {/* Main content */}
      <div className="flex-1 overflow-hidden">
        {state.viewMode === 'single' && currentImage && (
          <SinglePageView
            image={currentImage}
            brightness={state.brightness}
            onNext={nextPage}
            onPrev={prevPage}
            onToggleOverlay={handleToggleOverlay}
          />
        )}

        {state.viewMode === 'webtoon' && (
          <WebtoonView
            images={images}
            brightness={state.brightness}
            onPageChange={setPage}
          />
        )}

        {state.viewMode === 'double' && currentImage && (
          <DoublePageView
            leftImage={currentImage}
            rightImage={nextImage}
            brightness={state.brightness}
            onNext={() => setPage(state.currentPage + 2)}
            onPrev={() => setPage(state.currentPage - 2)}
            onToggleOverlay={handleToggleOverlay}
          />
        )}
      </div>

      {/* Bottom thumbnail strip */}
      {state.showOverlay && (
        <ThumbnailStrip
          images={images}
          currentPage={state.currentPage}
          onPageSelect={setPage}
        />
      )}
    </div>
  )
}
