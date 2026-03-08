'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import type { GalleryImage } from '@/lib/types'
import type { ReaderImage, ViewMode } from './types'
import {
  useReaderState,
  useSequentialPrefetch,
  useTouchGesture,
  useKeyboardNav,
  useProgressSave,
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

// ── Sub-components ────────────────────────────────────────────────────

interface SinglePageViewProps {
  image: ReaderImage
  isLoading: boolean
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
  onImageLoaded: () => void
}

function SinglePageView({
  image,
  isLoading,
  onNext,
  onPrev,
  onToggleOverlay,
  onImageLoaded,
}: SinglePageViewProps) {
  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden">
      <MediaElement
        image={image}
        className="max-h-full max-w-full object-contain pointer-events-none"
        draggable={false}
        onLoad={onImageLoaded}
      />
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40">
          <Spinner />
        </div>
      )}
      <div
        className="reader-tap-zone absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
        onClick={onPrev}
        aria-label="Previous page"
      />
      <div
        className="reader-tap-zone absolute left-[30%] top-0 h-full w-[40%] cursor-pointer select-none"
        onClick={onToggleOverlay}
        aria-label="Toggle controls"
      />
      <div
        className="reader-tap-zone absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
        onClick={onNext}
        aria-label="Next page"
      />
    </div>
  )
}

interface WebtoonViewProps {
  images: ReaderImage[]
  onPageChange: (page: number) => void
  onToggleOverlay: () => void
}

function WebtoonView({ images, onPageChange, onToggleOverlay }: WebtoonViewProps) {
  const elRefs = useRef<Map<number, HTMLElement>>(new Map())
  const scrollRef = useRef<HTMLDivElement>(null)
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set())
  const lastPage = images.length > 0 ? images[images.length - 1].pageNum : 0

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
          if (!isNaN(pageNum)) onPageChange(pageNum)
        }
      },
      { threshold: 0.5 },
    )

    elRefs.current.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [images, onPageChange])

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

interface DoublePageViewProps {
  leftImage: ReaderImage
  rightImage: ReaderImage | null
  isLoading: boolean
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
  onImageLoaded: () => void
}

function DoublePageView({
  leftImage,
  rightImage,
  isLoading,
  onNext,
  onPrev,
  onToggleOverlay,
  onImageLoaded,
}: DoublePageViewProps) {
  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden">
      <div className="flex h-full w-full flex-row">
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          <MediaElement
            image={leftImage}
            className="max-h-full max-w-full object-contain pointer-events-none"
            draggable={false}
            onLoad={onImageLoaded}
          />
        </div>
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          {rightImage ? (
            <MediaElement
              image={rightImage}
              className="max-h-full max-w-full object-contain pointer-events-none"
              draggable={false}
              onLoad={onImageLoaded}
            />
          ) : (
            <div className="h-full w-full" />
          )}
        </div>
      </div>
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40">
          <Spinner />
        </div>
      )}
      <div
        className="reader-tap-zone absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
        onClick={onPrev}
        aria-label="Previous page"
      />
      <div
        className="reader-tap-zone absolute left-[30%] top-0 h-full w-[40%] cursor-pointer select-none"
        onClick={onToggleOverlay}
        aria-label="Toggle controls"
      />
      <div
        className="reader-tap-zone absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
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
  onBack: () => void
  onViewModeChange: (mode: ViewMode) => void
}

function ReaderOverlay({
  currentPage,
  totalPages,
  viewMode,
  onBack,
  onViewModeChange,
}: ReaderOverlayProps) {
  const VIEW_MODES: ViewMode[] = ['single', 'webtoon', 'double']

  return (
    <div className="absolute top-0 left-0 right-0 z-20 flex items-center gap-3 bg-black/70 px-4 py-3 text-white text-sm backdrop-blur-sm">
      {/* Page indicator */}
      <span className="font-mono tabular-nums whitespace-nowrap">
        {currentPage} / {totalPages}
      </span>

      {/* Spacer */}
      <div className="flex-1" />

      {/* View mode buttons */}
      <div className="flex gap-1">
        {VIEW_MODES.map((m) => (
          <button
            key={m}
            onClick={() => onViewModeChange(m)}
            className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
              viewMode === m ? 'bg-white text-black' : 'bg-white/10 hover:bg-white/20 text-white'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Back button (right side) */}
      <button
        onClick={onBack}
        className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/20 shrink-0"
        title="Go back"
      >
        Back
      </button>
    </div>
  )
}

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

  const { state, setPage, nextPage, prevPage, setViewMode, toggleOverlay } = useReaderState(
    initialPage,
    totalPages,
  )

  const containerRef = useRef<HTMLDivElement>(null)

  // Track image loading state for single/double page views
  const [pageLoading, setPageLoading] = useState(false)
  const loadingPageRef = useRef(state.currentPage)

  // When page changes, mark as loading (single/double only)
  useEffect(() => {
    if (state.viewMode !== 'webtoon' && state.currentPage !== loadingPageRef.current) {
      setPageLoading(true)
      loadingPageRef.current = state.currentPage
    }
  }, [state.currentPage, state.viewMode])

  const handleImageLoaded = useCallback(() => {
    setPageLoading(false)
  }, [])

  useSequentialPrefetch(images, state.currentPage, isProxyMode)
  useProgressSave(galleryId, state.currentPage)

  useTouchGesture(containerRef as React.RefObject<HTMLElement | null>, nextPage, prevPage)

  useKeyboardNav(nextPage, prevPage)

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

  const currentImage = images.find((i) => i.pageNum === state.currentPage)
  const nextImage = images.find((i) => i.pageNum === state.currentPage + 1) ?? null

  return (
    <div ref={containerRef} className="reader-container flex flex-col bg-black">
      {/* Top overlay */}
      {state.showOverlay && (
        <ReaderOverlay
          currentPage={state.currentPage}
          totalPages={totalPages}
          viewMode={state.viewMode}
          onBack={handleBack}
          onViewModeChange={setViewMode}
        />
      )}

      {/* Main content */}
      <div className="flex-1 overflow-hidden">
        {state.viewMode === 'single' && currentImage && (
          <SinglePageView
            image={currentImage}
            isLoading={pageLoading}
            onNext={nextPage}
            onPrev={prevPage}
            onToggleOverlay={handleToggleOverlay}
            onImageLoaded={handleImageLoaded}
          />
        )}

        {state.viewMode === 'webtoon' && (
          <WebtoonView
            images={images}
            onPageChange={setPage}
            onToggleOverlay={handleToggleOverlay}
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
          />
        )}
      </div>

      {/* Bottom thumbnail strip */}
      {state.showOverlay && (
        <ThumbnailStrip
          images={images}
          currentPage={state.currentPage}
          onPageSelect={setPage}
          previews={previews}
        />
      )}
    </div>
  )
}
