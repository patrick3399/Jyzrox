'use client'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { getColumnCount, type ColumnConfig } from '@/components/VirtualGrid'
import { ThumbnailCell, type SpriteNaturalSizes } from './ThumbnailCell'
import type { ReaderImage, ReadingDirection } from './types'

export interface ThumbnailGridOverlayProps {
  images: ReaderImage[]
  currentPage: number
  /** Preview thumbs from EH CDN: { "1": "url" or "url|ox|w|h" } */
  previews?: Record<string, string>
  readingDirection?: ReadingDirection
  onSelect: (page: number) => void
  onClose: () => void
}

// Same 3:4 aspect ratio as ThumbnailStrip's fixed 60x80 frame, scaled to a
// fluid column width instead of a fixed pixel size.
const CELL_ASPECT = 80 / 60
const GAP = 8
const OVERSCAN_ROWS = 2
const COLUMNS: ColumnConfig = { base: 3, sm: 4, md: 6, lg: 8, xl: 10 }
// px-4 on the measured scroll container (see scrollRef below): getBoundingClientRect()
// returns the border-box, which already includes this padding, so it must be
// subtracted before dividing the remainder into columns — otherwise cellWidth is
// computed against space the grid never actually has, skewing every cell's aspect
// ratio away from the intended 3:4.
const HORIZONTAL_PADDING = 16 * 2

export function ThumbnailGridOverlay({
  images,
  currentPage,
  previews,
  readingDirection,
  onSelect,
  onClose,
}: ThumbnailGridOverlayProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // Seeded from window.innerWidth (same pattern as VirtualGrid.tsx), not 0.
  // @tanstack/react-virtual's own internal useIsomorphicLayoutEffect measures
  // and caches per-row offsets on the *first* render regardless of what this
  // component's JSX renders — a `containerWidth` of 0 on that first pass
  // computes a near-zero rowHeight, which gets cached permanently and never
  // updates even once later renders compute the real, correct rowHeight
  // (the cache only invalidates on an explicit DOM (re)measurement or a
  // count change, not because `estimateSize`'s return value changed). That
  // stale cache is what rendered multiple distinct rows on top of each other
  // near the top of the screen. Starting from a real width sidesteps the bad
  // first estimate entirely instead of trying to hide it after the fact.
  const [colCount, setColCount] = useState<number>(() =>
    typeof window === 'undefined' ? COLUMNS.base : getColumnCount(window.innerWidth, COLUMNS),
  )
  const [containerWidth, setContainerWidth] = useState<number>(() =>
    typeof window === 'undefined' ? 0 : window.innerWidth,
  )
  const [hasMeasured, setHasMeasured] = useState(false)

  // Sprite natural-size cache, independent of ThumbnailStrip's own copy.
  // Both read/write the same sprite sheet URLs, so a sheet already loaded by
  // the strip is served from the browser HTTP cache here — a second small
  // in-memory cache is far cheaper than plumbing a shared one across two
  // components that aren't guaranteed to be mounted at the same time.
  const [spriteNaturalSizes, setSpriteNaturalSizes] = useState<SpriteNaturalSizes>({})
  const spriteUrls = useMemo(() => {
    if (!previews) return []
    const urls = new Set<string>()
    for (const raw of Object.values(previews)) {
      if (raw.includes('|')) {
        urls.add(`/api/eh/thumb-proxy?url=${encodeURIComponent(raw.split('|')[0])}`)
      }
    }
    return [...urls]
  }, [previews])

  const displayImages = useMemo(
    () => (readingDirection === 'rtl' ? [...images].reverse() : images),
    [images, readingDirection],
  )

  // Refines the window.innerWidth estimate above to the scroll container's
  // *actual* content width (window.innerWidth doesn't know about this
  // overlay's own padding or any scrollbar), and keeps it in sync on resize.
  // useLayoutEffect (not useEffect) so this happens before paint — with a
  // plain useEffect the browser can paint one frame at the estimated width
  // first, which is a visible flash rather than a functional bug now that
  // the estimate is a real width instead of 0.
  //
  // Only apply a measurement that is actually usable (> 0). A width reading
  // of 0 is never more correct than the window.innerWidth estimate already
  // in state — it means this particular measurement path failed, not that
  // the container is genuinely zero-width — so it must not overwrite a good
  // estimate with a broken one.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const width = el.getBoundingClientRect().width
    if (width > 0) {
      setContainerWidth(width)
      setColCount(getColumnCount(width, COLUMNS))
    }
    setHasMeasured(true)

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const w = entry.contentRect.width
      if (w <= 0) return
      setContainerWidth(w)
      setColCount(getColumnCount(w, COLUMNS))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const rows = useMemo(() => {
    if (colCount <= 0 || displayImages.length === 0) return []
    const result: ReaderImage[][] = []
    for (let i = 0; i < displayImages.length; i += colCount) {
      result.push(displayImages.slice(i, i + colCount))
    }
    return result
  }, [displayImages, colCount])

  const cellWidth =
    colCount > 0
      ? Math.max(0, (containerWidth - HORIZONTAL_PADDING - GAP * (colCount - 1)) / colCount)
      : 0
  const cellHeight = cellWidth * CELL_ASPECT
  const rowHeight = cellHeight + GAP

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: OVERSCAN_ROWS,
  })

  // Align the initial scroll position to the row containing the current page.
  const didInitialScrollRef = useRef(false)
  useEffect(() => {
    if (!hasMeasured || didInitialScrollRef.current || colCount <= 0) return
    const idx = displayImages.findIndex((img) => img.pageNum === currentPage)
    if (idx < 0) return
    didInitialScrollRef.current = true
    virtualizer.scrollToIndex(Math.floor(idx / colCount), { align: 'start' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMeasured, colCount])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 flex flex-col bg-black/95"
      style={{ zIndex: 300 }} // above HelpOverlay (z-50) and ImageContextMenu (z-[200])
    >
      {/* Hidden imgs to learn natural sprite dimensions — same technique as ThumbnailStrip. */}
      {spriteUrls.map((proxyUrl) =>
        !spriteNaturalSizes[proxyUrl] ? (
          <img
            key={proxyUrl}
            src={proxyUrl}
            style={{ display: 'none' }}
            alt=""
            onLoad={(e) => {
              const { naturalWidth: w, naturalHeight: h } = e.currentTarget
              setSpriteNaturalSizes((prev) => (prev[proxyUrl] ? prev : { ...prev, [proxyUrl]: { w, h } }))
            }}
          />
        ) : null,
      )}

      <div
        className="flex items-center justify-between px-4 py-2 shrink-0"
        style={{ paddingTop: 'calc(0.5rem + env(safe-area-inset-top))' }}
      >
        <span className="text-sm text-white/70">{t('reader.gridOverview')}</span>
        <button
          onClick={onClose}
          aria-label={t('reader.closeGrid')}
          title={t('reader.closeGrid')}
          className="w-10 h-10 rounded bg-white/10 hover:bg-white/20 text-white flex items-center justify-center"
        >
          ✕
        </button>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4"
        style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
      >
        {!(cellWidth > 0) ? (
          <div className="flex justify-center py-8">
            <LoadingSpinner />
          </div>
        ) : (
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const rowItems = rows[virtualRow.index]
              if (!rowItems) return null
              return (
                <div
                  key={virtualRow.key}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    transform: `translateY(${virtualRow.start}px)`,
                    display: 'grid',
                    gridTemplateColumns: `repeat(${colCount}, minmax(0, 1fr))`,
                    gap: GAP,
                  }}
                >
                  {rowItems.map((img) => {
                    const previewRaw = previews?.[String(img.pageNum)]
                    return (
                      <div key={img.pageNum} style={{ height: cellHeight }}>
                        <ThumbnailCell
                          image={img}
                          isActive={img.pageNum === currentPage}
                          previewRaw={previewRaw}
                          spriteNaturalSizes={spriteNaturalSizes}
                          frameWidth={Math.round(cellWidth)}
                          frameHeight={Math.round(cellHeight)}
                          onSelect={(page) => {
                            onSelect(page)
                            onClose()
                          }}
                        />
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
