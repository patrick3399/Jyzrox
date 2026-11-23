'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReaderImage, ScaleMode, ReadingDirection } from './types'
import { t } from '@/lib/i18n'
import { usePinchZoom } from './hooks'
import { Spinner } from './Spinner'
import { getScaleImageClass } from './scaleClasses'
import { RetryLayerContext } from './ReaderImg'
import { PageSlot } from './PageSlot'
import { useSlotSettlement, waitsForDecode } from './slotSettlement'
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

  // Hold the outgoing pair on screen until both incoming pages can be painted.
  // Each half mounts one element per page, and a new element stays invisible
  // until it has loaded and decoded (FE-T34); swapping straight away showed
  // the black background on every turn. Each half tracks its own elements: a
  // page that moves to the other half (RTL toggle) is a new element there.
  const firstSettlement = useSlotSettlement()
  const secondSettlement = useSlotSettlement()
  const pairReady =
    sideReady(firstImage, firstSettlement.isSettled) &&
    sideReady(secondImage, secondSettlement.isSettled)
  const [shownPair, setShownPair] = useState<ShownPair | null>(null)
  if (
    pairReady &&
    (shownPair == null ||
      !samePage(shownPair.first, firstImage) ||
      !samePage(shownPair.second, secondImage))
  ) {
    setShownPair({ first: firstImage, second: secondImage })
  }
  const holding =
    !pairReady &&
    shownPair != null &&
    (shownPair.first != null || shownPair.second != null) &&
    sideHoldable(shownPair.first, firstSettlement.isSettled) &&
    sideHoldable(shownPair.second, secondSettlement.isSettled)

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
        <DoubleHalf
          current={firstImage}
          holding={holding}
          held={shownPair?.first ?? null}
          settlement={firstSettlement}
          retryLayer={firstRetryLayer}
          imgClass={imgClass}
          onImageLoaded={onImageLoaded}
          onImageError={onImageError}
          onToggleOverlay={onToggleOverlay}
          showOverlay={showOverlay}
          imageLongPress={imageLongPress}
        />
        <DoubleHalf
          current={secondImage}
          holding={holding}
          held={shownPair?.second ?? null}
          settlement={secondSettlement}
          retryLayer={secondRetryLayer}
          imgClass={imgClass}
          onImageLoaded={onImageLoaded}
          onImageError={onImageError}
          onToggleOverlay={onToggleOverlay}
          showOverlay={showOverlay}
          imageLongPress={imageLongPress}
        />
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

interface ShownPair {
  first: ReaderImage | null
  second: ReaderImage | null
}

type IsSettled = (image: ReaderImage) => boolean

function samePage(a: ReaderImage | null, b: ReaderImage | null): boolean {
  if (a == null || b == null) return a === b
  return a.pageNum === b.pageNum && a.url === b.url
}

/** The incoming page of a half no longer needs the outgoing pair held. */
function sideReady(image: ReaderImage | null, isSettled: IsSettled): boolean {
  return !waitsForDecode(image) || isSettled(image)
}

/** The outgoing page of a half can still be painted (or the half was empty). */
function sideHoldable(image: ReaderImage | null, isSettled: IsSettled): boolean {
  return image == null || (waitsForDecode(image) && isSettled(image))
}

function DoubleHalf({
  current,
  holding,
  held,
  settlement,
  retryLayer,
  imgClass,
  onImageLoaded,
  onImageError,
  onToggleOverlay,
  showOverlay,
  imageLongPress,
}: {
  current: ReaderImage | null
  /** Show `held` (the outgoing pair's page, null if the half was empty) instead of `current`. */
  holding: boolean
  held: ReaderImage | null
  settlement: ReturnType<typeof useSlotSettlement>
  retryLayer: HTMLDivElement | null
  imgClass: string
  onImageLoaded: () => void
  onImageError: () => void
  onToggleOverlay: () => void
  showOverlay: boolean
  imageLongPress?: (pageNum: number, imageUrl: string) => ImageLongPressHandlers
}) {
  const slots: ReaderImage[] = current ? [current] : []
  if (holding && held && held.pageNum !== current?.pageNum) slots.push(held)
  const visiblePage = holding ? (held?.pageNum ?? null) : (current?.pageNum ?? null)
  const lp =
    imageLongPress && current?.url ? imageLongPress(current.pageNum, current.url) : undefined

  return (
    <div className="flex h-full w-1/2 items-center justify-center overflow-hidden">
      {slots.length > 0 ? (
        <div
          className="w-full h-full flex items-center justify-center"
          onTouchStart={lp?.onTouchStart}
          onTouchMove={lp?.onTouchMove}
          onTouchEnd={lp?.onTouchEnd}
          onContextMenu={lp?.onContextMenu}
        >
          {slots.map((slot) => (
            // Only the current page may put its notice in the layer.
            <RetryLayerContext.Provider
              key={slot.pageNum}
              value={slot === current ? retryLayer : null}
            >
              <PageSlot
                image={slot}
                isCurrent={slot === current}
                visible={slot.pageNum === visiblePage}
                className={imgClass}
                onCurrentLoaded={onImageLoaded}
                onCurrentError={onImageError}
                onSlotSettled={settlement.markSettled}
                onSlotUnmounted={settlement.forget}
                onToggleOverlay={onToggleOverlay}
                overlayVisible={showOverlay}
              />
            </RetryLayerContext.Provider>
          ))}
        </div>
      ) : (
        <div className="h-full w-full" />
      )}
    </div>
  )
}
