'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReaderImage, ScaleMode, ReadingDirection } from './types'
import { t } from '@/lib/i18n'
import { usePinchZoom } from './hooks'
import { Spinner } from './Spinner'
import { getScaleContainerClass, getScaleImageClass } from './scaleClasses'
import { RetryLayerContext } from './ReaderImg'
import { PageSlot } from './PageSlot'
import type { ImageLongPressHandlers } from './viewTypes'

interface SinglePageViewProps {
  image: ReaderImage
  prevImage: ReaderImage | null
  nextImage: ReaderImage | null
  /** Pages the prefetcher has finished with; a neighbour is only mounted once it is here. */
  prefetchedPages: ReadonlySet<number>
  isLoading: boolean
  onNext: () => void
  onPrev: () => void
  onToggleOverlay: () => void
  onImageLoaded: () => void
  onImageError: () => void
  scaleMode: ScaleMode
  readingDirection: ReadingDirection
  showOverlay: boolean
  currentPage: number
  onZoomChange?: (isZoomed: boolean) => void
  imageLongPress?: ImageLongPressHandlers
}

export function SinglePageView({
  image,
  prevImage,
  nextImage,
  prefetchedPages,
  isLoading,
  onNext,
  onPrev,
  onToggleOverlay,
  onImageLoaded,
  onImageError,
  scaleMode,
  readingDirection,
  showOverlay,
  currentPage,
  onZoomChange,
  imageLongPress,
}: SinglePageViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // Center tap zone: delay toggle to prevent double-tap from also toggling overlay.
  // isDoubleTapRef is set by usePinchZoom's native touchend listener (fires before any click),
  // covering both modern browsers (click fires immediately) and iOS (300ms click delay).
  const centerTapTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const isDoubleTapRef = useRef(false)
  const clearDoubleTap = useCallback(() => {
    isDoubleTapRef.current = false
  }, [])
  useEffect(() => () => clearTimeout(centerTapTimerRef.current), [])
  const { isZoomed, transform, isGesturing } = usePinchZoom(
    containerRef as React.RefObject<HTMLElement | null>,
    currentPage,
    () => {
      // Called synchronously when double-tap is confirmed — before click fires
      isDoubleTapRef.current = true
      clearTimeout(centerTapTimerRef.current)
      centerTapTimerRef.current = undefined
    },
  )

  useEffect(() => {
    onZoomChange?.(isZoomed)
  }, [isZoomed, onZoomChange])

  const leftAction = readingDirection === 'rtl' ? onNext : onPrev
  const rightAction = readingDirection === 'rtl' ? onPrev : onNext
  // A mounted player takes the centre tap itself and shows its controls with
  // the overlay, so the edge zones only have to step aside while those are up
  // (FE-T8). A video with no file yet mounts no player and is tapped like an image.
  const playerMounted = image.mediaType === 'video' && image.url != null
  const edgeZones = !isZoomed && (!playerMounted || !showOverlay)

  // Pages whose bytes are known to be local: loaded here as a slot, or reported
  // by the prefetcher. Only these are retained, so keeping a neighbour mounted
  // pins it in memory but never starts a download next to the prefetcher's.
  const [loadedPages, setLoadedPages] = useState<ReadonlySet<number>>(() => new Set())
  const markSlotLoaded = useCallback((pageNum: number) => {
    setLoadedPages((prev) => (prev.has(pageNum) ? prev : new Set(prev).add(pageNum)))
  }, [])
  // Videos are never retained: a hidden <video> still buffers (FE-T16).
  const retainable = (candidate: ReaderImage | null): candidate is ReaderImage =>
    candidate != null &&
    candidate.mediaType === 'image' &&
    candidate.url != null &&
    (loadedPages.has(candidate.pageNum) || prefetchedPages.has(candidate.pageNum))
  const slots = [prevImage, image, nextImage].filter(
    (slot): slot is ReaderImage => slot === image || retainable(slot),
  )
  const [retryLayer, setRetryLayer] = useState<HTMLDivElement | null>(null)

  return (
    <div
      ref={containerRef}
      className={`${getScaleContainerClass(scaleMode)} h-full w-full`}
      // usePinchZoom cancels a double-tap's touchend, so its click never comes
      // to consume isDoubleTapRef; clear it when the next touch begins, or that
      // tap's click is swallowed.
      onTouchStartCapture={clearDoubleTap}
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
        {slots.map((slot) => (
          // Only the page on screen may put its notice in the layer; a retained
          // neighbour is hidden and keeps its own inside its hidden box.
          <RetryLayerContext.Provider key={slot.pageNum} value={slot === image ? retryLayer : null}>
            <PageSlot
              image={slot}
              isCurrent={slot === image}
              className={getScaleImageClass(scaleMode)}
              onCurrentLoaded={onImageLoaded}
              onCurrentError={onImageError}
              onSlotLoaded={markSlotLoaded}
              onToggleOverlay={onToggleOverlay}
              overlayVisible={showOverlay}
            />
          </RetryLayerContext.Provider>
        ))}
      </div>
      {isLoading && (
        <div
          data-testid="reader-page-loading"
          className="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none"
        >
          <Spinner />
        </div>
      )}
      {!playerMounted && (
        <>
          {/* Center zone — always visible (even when zoomed) for overlay toggle */}
          <div
            className={`reader-tap-zone absolute cursor-pointer select-none ${readingDirection === 'vertical' ? 'top-[30%] left-0 w-full h-[40%]' : 'left-[30%] top-0 h-full w-[40%]'}`}
            onClick={(e) => {
              e.stopPropagation()
              if (isDoubleTapRef.current) {
                isDoubleTapRef.current = false
                return
              }
              clearTimeout(centerTapTimerRef.current)
              centerTapTimerRef.current = setTimeout(() => onToggleOverlay(), 250)
            }}
            aria-label={t('reader.toggleControls')}
          />
        </>
      )}
      {edgeZones && (
        <>
          {/* Prev / Next zones — hidden when zoomed (user pans instead) */}
          {readingDirection === 'vertical' && (
            <>
              <div
                className="reader-tap-zone absolute top-0 left-0 w-full h-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) {
                    isDoubleTapRef.current = false
                    return
                  }
                  onPrev()
                }}
                aria-label={t('common.previousPage')}
              />
              <div
                className="reader-tap-zone absolute bottom-0 left-0 w-full h-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) {
                    isDoubleTapRef.current = false
                    return
                  }
                  onNext()
                }}
                aria-label={t('common.nextPage')}
              />
            </>
          )}
          {readingDirection !== 'vertical' && (
            <>
              <div
                className="reader-tap-zone absolute left-0 top-0 h-full w-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) {
                    isDoubleTapRef.current = false
                    return
                  }
                  leftAction()
                }}
                aria-label={
                  readingDirection === 'rtl' ? t('common.nextPage') : t('common.previousPage')
                }
              />
              <div
                className="reader-tap-zone absolute right-0 top-0 h-full w-[30%] cursor-pointer select-none"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isDoubleTapRef.current) {
                    isDoubleTapRef.current = false
                    return
                  }
                  rightAction()
                }}
                aria-label={
                  readingDirection === 'rtl' ? t('common.previousPage') : t('common.nextPage')
                }
              />
            </>
          )}
        </>
      )}
      {/* Above the tap zones: see RetryLayerContext. */}
      <div
        ref={setRetryLayer}
        className="pointer-events-none absolute inset-0 flex items-center justify-center"
      />
    </div>
  )
}
