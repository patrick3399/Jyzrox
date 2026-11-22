'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import type { Gallery, GalleryImage } from '@/lib/types'
import type { ReaderImage, ReaderSettings } from './types'
import { DEFAULT_READER_SETTINGS } from './types'
import { t } from '@/lib/i18n'
import { api } from '@/lib/api'
import { galleryHref } from '@/lib/galleryRoutes'
import { smartBack } from '@/lib/navBack'
import { toast } from 'sonner'
import {
  useReaderState,
  useSequentialPrefetch,
  useTouchGesture,
  useKeyboardNav,
  useProgressSave,
  useAutoAdvance,
  loadReaderSettings,
  saveReaderSettings,
} from './hooks'
import { ImageContextMenu } from './ImageContextMenu'
import { LazySauceNaoModal } from '@/components/LazyDialogs'
import { isGalleryInProgress } from '@/lib/readerRefresh'
import { pagePosition, sortPageNums, stepPage } from './pageOrder'
import { HelpOverlay, StatusBar } from './ReaderChrome'
import { ThumbnailGridOverlay } from './ThumbnailGridOverlay'
import { READER_CHROME_SELECTOR } from './scaleClasses'
import type { ImageLongPressHandlers } from './viewTypes'
import { SinglePageView } from './SinglePageView'
import { WebtoonView } from './WebtoonView'
import { DoublePageView } from './DoublePageView'
import { ReaderOverlay } from './ReaderOverlay'
import { ThumbnailStrip } from './ThumbnailStrip'

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

const NO_PAGES: ReadonlySet<number> = new Set()

interface ReaderProps {
  source: string
  sourceId: string
  downloadStatus: Gallery['download_status']
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
  /** Where every exit goes when history has nothing to go back to (share link,
   *  new tab, PWA relaunch) or the URL was restored by a nav tab. Required: a
   *  reader route has no app chrome and no swipe-back, so without it an exit on
   *  a one-entry history would trap the user. */
  backHref: string
}

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
  backHref,
}: ReaderProps) {
  const router = useRouter()
  const isProxyMode = downloadStatus === 'proxy_only'

  const [hiddenPages, setHiddenPages] = useState<Set<number>>(new Set())
  const [favImageIds, setFavImageIds] = useState<Set<number>>(
    () => new Set(initialFavoritedImageIds ?? []),
  )

  const pageOrder = useMemo(
    () => sortPageNums(rawImages.map((img) => img.page_num).filter((p) => !hiddenPages.has(p))),
    [rawImages, hiddenPages],
  )
  // Once no more pages can arrive, the list is the gallery: the Reader walks it
  // and counts along it, so holes in page_num are neither shown nor counted.
  const settledPages =
    !isProxyMode && !isGalleryInProgress(downloadStatus) && pageOrder.length > 0 ? pageOrder : null

  // Memoized: this array feeds effects in the prefetch hook and the webtoon
  // observer. Rebuilding it on every render made those effects re-run on every
  // render — including the ones triggered by a prefetch settling — which tore
  // down and re-issued in-flight media requests in a loop.
  const images: ReaderImage[] = useMemo(
    () =>
      rawImages
        .filter((img) => !hiddenPages.has(img.page_num))
        .map((img) => ({
          pageNum: img.page_num,
          position: settledPages ? pagePosition(settledPages, img.page_num) : undefined,
          url: resolveImageUrl(img, source, sourceId),
          isLocal: img.file_path != null,
          width: img.width ?? undefined,
          height: img.height ?? undefined,
          mediaType: img.media_type,
          duration: img.duration ?? undefined,
          thumbUrl: img.thumb_path?.replace('/data/', '/media/') ?? undefined,
          thumbhash: img.thumbhash ?? null,
        })),
    [rawImages, hiddenPages, settledPages, source, sourceId],
  )

  const {
    state,
    setPage,
    nextPage: rawNextPage,
    prevPage: rawPrevPage,
    setViewMode,
    toggleOverlay,
    setScaleMode,
    setReadingDirection,
    showGrid,
    hideGrid,
  } = useReaderState(
    initialPage,
    // A download can have imported pages numbered above its running count.
    Math.max(totalPages, pageOrder[pageOrder.length - 1] ?? 0),
    source,
    sourceId,
    settledPages,
  )

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

  const shownPage = settledPages ? pagePosition(settledPages, state.currentPage) : state.currentPage
  const shownTotalPages = settledPages ? settledPages.length : totalPages - hiddenPages.size
  const isLastPage =
    pageOrder.length > 0 ? state.currentPage >= pageOrder[pageOrder.length - 1] : true

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
  // Starts empty so the page-change effect also arms the spinner for the page
  // the Reader opens on; seeding it with that page skipped it, and a slow or
  // stuck first page showed no loading state at all.
  const loadingPageRef = useRef<number | null>(null)
  const loadedPagesRef = useRef<Set<number>>(new Set())
  const loadingTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // The page whose image has settled (loaded, or failed after ReaderImg's
  // retries). Proxy prefetch waits for the page on screen to settle so its
  // neighbours do not compete with it for the server's EH request slots.
  const [settledPage, setSettledPage] = useState<number | null>(null)

  const handleImageLoaded = useCallback(() => {
    // Remember the load only while the page-change effect has not run for this
    // page yet (load fired first). After that the entry has no consumer and
    // would outlive this visit, making the next visit to the page skip the
    // spinner timer even though the image has to load again.
    if (loadingPageRef.current !== state.currentPage) {
      loadedPagesRef.current.add(state.currentPage)
    }
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current)
      loadingTimerRef.current = undefined
    }
    setPageLoading(false)
    setSettledPage(state.currentPage)
  }, [state.currentPage])

  // On image load failure, stop the spinner (ReaderImg shows its own retry placeholder).
  const handleImageError = useCallback(() => {
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current)
      loadingTimerRef.current = undefined
    }
    setPageLoading(false)
    setSettledPage(state.currentPage)
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

  // The page indicator and status bar speak in the numbers they show.
  const selectShownPage = useCallback(
    (shown: number) => setPageWithPrefetch(settledPages ? settledPages[shown - 1] : shown),
    [settledPages, setPageWithPrefetch],
  )

  const pageAfter = (delta: number) =>
    settledPages ? stepPage(settledPages, state.currentPage, delta) : state.currentPage + delta

  // Webtoon mounts every page and loads them as they near the viewport, so no
  // single page load gates it.
  const prefetchedPages = useSequentialPrefetch(images, state.currentPage, isProxyMode, {
    currentPageReady: state.viewMode === 'webtoon' || settledPage === state.currentPage,
  })
  useProgressSave(source, sourceId, state.currentPage, !isProxyMode)

  const handleToggleOverlay = useCallback(() => toggleOverlay(), [toggleOverlay])
  // Reader routes have no chrome and no swipe-back, so every exit must resolve
  // like the back FAB: a no-op router.back() on a one-entry history would trap
  // the user, and a tab-restored URL must climb instead of leaving the section.
  const handleBack = useCallback(() => smartBack(router, backHref), [router, backHref])

  // Track viewMode in ref so swipe callbacks stay stable across mode changes
  const viewModeRef = useRef(state.viewMode)
  useEffect(() => {
    viewModeRef.current = state.viewMode
  }, [state.viewMode])

  // Swipe: respect RTL direction; in webtoon mode, swipeRight = go back
  const swipeLeft = useCallback(() => {
    if (state.readingDirection === 'rtl') rawPrevPage()
    else rawNextPage()
  }, [state.readingDirection, rawNextPage, rawPrevPage])

  const swipeRight = useCallback(() => {
    if (viewModeRef.current === 'webtoon') {
      handleBack()
      return
    }
    if (state.readingDirection === 'rtl') rawNextPage()
    else rawPrevPage()
  }, [state.readingDirection, rawNextPage, rawPrevPage, handleBack])

  const handleSwipeUp = useCallback(() => {
    if (viewModeRef.current !== 'webtoon') handleBack()
  }, [handleBack])

  const isZoomedRef = useRef(false)
  // Set once the image long-press menu is up: a finger that slides on after the
  // menu opened is reaching for an item, not swiping the page underneath.
  const imageMenuOpenRef = useRef(false)
  const handleZoomChange = useCallback((z: boolean) => {
    isZoomedRef.current = z
  }, [])

  useTouchGesture(
    containerRef as React.RefObject<HTMLElement | null>,
    swipeLeft,
    swipeRight,
    handleSwipeUp,
    50,
    // Scrolling inside the grid overview bubbles touch events up to this
    // listener on containerRef; without this guard a downward scroll
    // (finger swiping up) inside the grid was misread as swipe-up-to-back
    // and exited the Reader instead of just scrolling the grid.
    () => isZoomedRef.current || imageMenuOpenRef.current || state.isGridOpen,
    // Scrolling the thumbnail strip or dragging the seek bar is not a page swipe.
    READER_CHROME_SELECTOR,
  )

  useKeyboardNav(
    () => {
      if (!state.isGridOpen) rawNextPage()
    },
    () => {
      if (!state.isGridOpen) rawPrevPage()
    },
    () => {
      if (!state.isGridOpen) handleToggleOverlay()
    },
    () => {
      if (!state.isGridOpen) handleBack()
    },
    state.readingDirection,
    state.viewMode,
  )

  // Mouse wheel: scroll down → next page, scroll up → prev page (single/double only)
  // Webtoon mode uses native continuous scrolling (like mobile touch)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    if (state.viewMode === 'webtoon') return
    let cooldown = false
    const handler = (e: WheelEvent) => {
      // Don't intercept wheel events on the overlay controls, the thumbnail strip
      // (it has its own horizontal scroll) or the status bar
      if ((e.target as HTMLElement)?.closest(READER_CHROME_SELECTOR)) return
      if (cooldown) return
      const dy = e.deltaY
      if (Math.abs(dy) < 10) return
      e.preventDefault()
      cooldown = true
      setTimeout(() => {
        cooldown = false
      }, 200)
      if (dy > 0) rawNextPage()
      else rawPrevPage()
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [rawNextPage, rawPrevPage, state.viewMode])

  // Escape key to go back — no-ops while the grid overview is open, which
  // has its own Escape handler to close itself instead.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (state.isGridOpen) return
        handleBack()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleBack, state.isGridOpen])

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

  const [saucenaoImageId, setSaucenaoImageId] = useState<number | null>(null)

  useEffect(() => {
    imageMenuOpenRef.current = imageMenu?.open ?? false
  }, [imageMenu])

  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const longPressStartRef = useRef<{ x: number; y: number } | null>(null)

  const cancelImageLongPress = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
    longPressStartRef.current = null
  }, [])

  const makeImageLongPressHandlers = useCallback(
    (imageUrl: string, imageName: string, pageNum: number): ImageLongPressHandlers => ({
      onTouchStart: (e: React.TouchEvent) => {
        // Every touchstart (including a pinch's second finger) replaces the
        // pending timer; overwriting the ref without clearing it orphaned the
        // first timer, which then opened the menu mid-pinch.
        cancelImageLongPress()
        // Only a single resting finger is a long-press; two fingers are a pinch.
        if (e.touches.length !== 1) return
        const touch = e.touches[0]
        longPressStartRef.current = { x: touch.clientX, y: touch.clientY }
        longPressTimerRef.current = setTimeout(() => {
          longPressTimerRef.current = null
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
        if (e.touches.length !== 1) {
          cancelImageLongPress()
          return
        }
        const touch = e.touches[0]
        const dx = touch.clientX - longPressStartRef.current.x
        const dy = touch.clientY - longPressStartRef.current.y
        if (Math.sqrt(dx * dx + dy * dy) > 10) cancelImageLongPress()
      },
      onTouchEnd: cancelImageLongPress,
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
    [cancelImageLongPress],
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
        handleBack()
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
  }, [
    imageMenu,
    source,
    sourceId,
    rawImages,
    hiddenPages,
    state.currentPage,
    setPage,
    handleBack,
    onHideImage,
  ])

  const handleViewGallery = useCallback(() => {
    const img = imageMenu ? rawImages.find((i) => i.page_num === imageMenu.pageNum) : undefined
    const crossGalleryImg = img as
      | (GalleryImage & { gallery_source?: string | null; gallery_source_id?: string | null })
      | undefined
    const gallerySource = crossGalleryImg?.gallery_source ?? source
    const gallerySourceId = crossGalleryImg?.gallery_source_id ?? sourceId
    if (!gallerySource || !gallerySourceId) return
    router.push(galleryHref(gallerySource, gallerySourceId))
    setImageMenu(null)
  }, [imageMenu, rawImages, source, sourceId, router])

  const handleToggleFavorite = useCallback(async () => {
    if (!imageMenu) return
    const img = rawImages.find((i) => i.page_num === imageMenu.pageNum)
    if (!img?.id) return

    const isFav = favImageIds.has(img.id)
    setImageMenu(null) // close menu first

    try {
      if (isFav) {
        await api.library.unfavoriteImage(img.id)
        setFavImageIds((prev) => {
          const next = new Set(prev)
          next.delete(img.id)
          return next
        })
        toast.success(t('reader.imageUnfavorited'))
      } else {
        await api.library.favoriteImage(img.id)
        setFavImageIds((prev) => new Set(prev).add(img.id))
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
  // pageAfter() stays put at either end of a settled list.
  const prevPageNum = pageAfter(-1)
  const nextPageNum = pageAfter(1)
  const prevImage =
    prevPageNum !== state.currentPage
      ? (images.find((i) => i.pageNum === prevPageNum) ?? null)
      : null
  const nextImage =
    nextPageNum !== state.currentPage
      ? (images.find((i) => i.pageNum === nextPageNum) ?? null)
      : null

  // When downloading progressively, the current page may not have been imported yet.
  const isDownloading = downloadStatus === 'downloading'
  const pageNotReady = !currentImage && isDownloading && images.length > 0

  // Compute favorite eligibility for current context menu image
  const contextMenuImg = imageMenu
    ? rawImages.find((i) => i.page_num === imageMenu.pageNum)
    : undefined
  const canFavoriteContextImg =
    !isProxyMode && contextMenuImg?.id != null && contextMenuImg?.file_path != null
  const currentSourceWork = rawImages.find(
    (image) => image.page_num === state.currentPage,
  )?.source_work

  return (
    <div ref={containerRef} className="reader-container flex flex-col bg-black">
      {/* Top overlay — always rendered, slides in/out */}
      <div
        className={`reader-overlay absolute top-0 left-0 right-0 z-20 transition-transform duration-300 ${
          state.showOverlay ? 'translate-y-0' : '-translate-y-full'
        } ${!state.showOverlay ? 'pointer-events-none' : ''}`}
      >
        <ReaderOverlay
          currentPage={shownPage}
          totalPages={shownTotalPages}
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
          onPageSelect={selectShownPage}
          onOpenGrid={showGrid}
        />
      </div>

      {currentSourceWork && state.showOverlay && (
        <a
          href={currentSourceWork.source_item_url || undefined}
          target="_blank"
          rel="noopener noreferrer"
          className={`absolute top-16 left-1/2 z-20 max-w-[80vw] -translate-x-1/2 rounded-lg bg-black/75 px-3 py-1.5 text-center text-xs text-white backdrop-blur ${
            currentSourceWork.status === 'source_missing' ? 'text-amber-300' : ''
          }`}
        >
          {currentSourceWork.title || currentSourceWork.source_item_id}
          {currentSourceWork.status === 'source_missing' &&
            ` · ${t('pixiv.collectionSourceMissing')}`}
        </a>
      )}

      {/* Main content — absolute inset-0 gives children a definite height so h-full resolves
          correctly on iOS Safari even during CSS transitions on sibling overlay elements. */}
      <div className="absolute inset-0 overflow-hidden">
        {state.viewMode === 'single' && currentImage && (
          <SinglePageView
            image={currentImage}
            prevImage={prevImage}
            nextImage={nextImage}
            // Proxy mode: a prefetch that errored (pToken not in Redis yet) is
            // also reported as settled, and pre-mounting it would start
            // ReaderImg's auto-retry backoff before the user arrives (FE-T15).
            prefetchedPages={isProxyMode ? NO_PAGES : prefetchedPages}
            isLoading={pageLoading}
            onNext={rawNextPage}
            onPrev={rawPrevPage}
            onToggleOverlay={handleToggleOverlay}
            onImageLoaded={handleImageLoaded}
            onImageError={handleImageError}
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
            onNext={() => setPageWithPrefetch(pageAfter(2))}
            onPrev={() => setPageWithPrefetch(pageAfter(-2))}
            onToggleOverlay={handleToggleOverlay}
            onImageLoaded={handleImageLoaded}
            onImageError={handleImageError}
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
        className={`reader-overlay absolute bottom-0 left-0 right-0 z-20 transition-transform duration-300 ${
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
        className={`reader-overlay absolute left-0 right-0 bottom-0 z-10 transition-opacity duration-300 ${state.showOverlay ? 'opacity-0' : 'opacity-100'}`}
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <StatusBar
          currentPage={shownPage}
          totalPages={shownTotalPages}
          settings={readerSettings}
          countdown={countdown}
          autoAdvanceEnabled={autoAdvanceEnabled}
          onPageSelect={selectShownPage}
          readingDirection={state.readingDirection}
        />
      </div>

      {/* Help overlay */}
      {showHelp && (
        <HelpOverlay
          readingDirection={state.readingDirection}
          viewMode={state.viewMode}
          onDismiss={handleDismissHelp}
        />
      )}

      {/* Full-screen thumbnail grid overview */}
      {state.isGridOpen && (
        <ThumbnailGridOverlay
          images={images}
          currentPage={state.currentPage}
          previews={previews}
          readingDirection={state.readingDirection}
          onSelect={setPageWithPrefetch}
          onClose={hideGrid}
        />
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
            (imageMenu.pageNum && images.find((i) => i.pageNum === imageMenu.pageNum)?.isLocal) ||
            onHideImage
              ? handleHideImage
              : undefined
          }
          isFavorited={
            canFavoriteContextImg && contextMenuImg ? favImageIds.has(contextMenuImg.id) : undefined
          }
          onToggleFavorite={canFavoriteContextImg ? handleToggleFavorite : undefined}
          onViewGallery={
            source ||
            sourceId ||
            (
              contextMenuImg as
                | (GalleryImage & {
                    gallery_source?: string | null
                    gallery_source_id?: string | null
                  })
                | undefined
            )?.gallery_source
              ? handleViewGallery
              : undefined
          }
          onFindSource={
            canFavoriteContextImg && contextMenuImg
              ? () => {
                  setSaucenaoImageId(contextMenuImg.id)
                  setImageMenu(null)
                }
              : undefined
          }
        />
      )}

      {saucenaoImageId && (
        <LazySauceNaoModal imageId={saucenaoImageId} onClose={() => setSaucenaoImageId(null)} />
      )}
    </div>
  )
}

export { ReaderImg } from './ReaderImg'
