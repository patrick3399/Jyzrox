'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReaderImage, ScaleMode, ReadingDirection } from './types'
import { t } from '@/lib/i18n'
import { usePinchZoom } from './hooks'
import { Spinner } from './Spinner'
import { getScaleImageClass } from './scaleClasses'
import { RetryLayerContext } from './ReaderImg'
import { MediaElement } from './MediaElement'
import type { ImageLongPressHandlers } from './viewTypes'

interface DoublePageViewProps {
  leftImage: ReaderImage
  rightImage: ReaderImage | null
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
  imageLongPress?: (pageNum: number, imageUrl: string) => ImageLongPressHandlers
}

export function DoublePageView({
  leftImage,
  rightImage,
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
}: DoublePageViewProps) {
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

  // RTL: swap display order
  const firstImage = readingDirection === 'rtl' ? rightImage : leftImage
  const secondImage = readingDirection === 'rtl' ? leftImage : rightImage

  const imgClass = getScaleImageClass(scaleMode === 'fit-both' ? 'fit-both' : scaleMode)
  const [firstRetryLayer, setFirstRetryLayer] = useState<HTMLDivElement | null>(null)
  const [secondRetryLayer, setSecondRetryLayer] = useState<HTMLDivElement | null>(null)
  // Same rule as SinglePageView: edge zones yield only to visible player controls.
  const playerMounted = [leftImage, rightImage].some(
    (candidate) => candidate?.mediaType === 'video' && candidate.url != null,
  )
  const edgeZones = !isZoomed && (!playerMounted || !showOverlay)

  return (
    <div
      ref={containerRef}
      className="relative flex h-full w-full items-center justify-center overflow-hidden"
      // usePinchZoom cancels a double-tap's touchend, so its click never comes
      // to consume isDoubleTapRef; clear it when the next touch begins, or that
      // tap's click is swallowed.
      onTouchStartCapture={clearDoubleTap}
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
          {firstImage ? (
            (() => {
              const lp =
                imageLongPress && firstImage.url
                  ? imageLongPress(firstImage.pageNum, firstImage.url)
                  : undefined
              return (
                <div
                  className="w-full h-full flex items-center justify-center"
                  onTouchStart={lp?.onTouchStart}
                  onTouchMove={lp?.onTouchMove}
                  onTouchEnd={lp?.onTouchEnd}
                  onContextMenu={lp?.onContextMenu}
                >
                  <RetryLayerContext.Provider value={firstRetryLayer}>
                    <MediaElement
                      image={firstImage}
                      className={imgClass}
                      draggable={false}
                      onLoad={onImageLoaded}
                      onError={onImageError}
                      onToggleOverlay={onToggleOverlay}
                      overlayVisible={showOverlay}
                    />
                  </RetryLayerContext.Provider>
                </div>
              )
            })()
          ) : (
            <div className="h-full w-full" />
          )}
        </div>
        <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
          {secondImage ? (
            (() => {
              const lp =
                imageLongPress && secondImage.url
                  ? imageLongPress(secondImage.pageNum, secondImage.url)
                  : undefined
              return (
                <div
                  className="w-full h-full flex items-center justify-center"
                  onTouchStart={lp?.onTouchStart}
                  onTouchMove={lp?.onTouchMove}
                  onTouchEnd={lp?.onTouchEnd}
                  onContextMenu={lp?.onContextMenu}
                >
                  <RetryLayerContext.Provider value={secondRetryLayer}>
                    <MediaElement
                      image={secondImage}
                      className={imgClass}
                      draggable={false}
                      onLoad={onImageLoaded}
                      onError={onImageError}
                      onToggleOverlay={onToggleOverlay}
                      overlayVisible={showOverlay}
                    />
                  </RetryLayerContext.Provider>
                </div>
              )
            })()
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
      {/* Above the tap zones, one half per page: see RetryLayerContext. */}
      <div className="pointer-events-none absolute inset-0 flex flex-row">
        <div ref={setFirstRetryLayer} className="flex h-full w-1/2 items-center justify-center" />
        <div ref={setSecondRetryLayer} className="flex h-full w-1/2 items-center justify-center" />
      </div>
    </div>
  )
}
