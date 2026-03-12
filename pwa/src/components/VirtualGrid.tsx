'use client'

import { useRef, useEffect, useState, useMemo } from 'react'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { LoadingSpinner } from '@/components/LoadingSpinner'

// Map of Tailwind breakpoints to column counts (px)
export interface ColumnConfig {
  base: number    // default cols (mobile)
  sm?: number     // >= 640px
  md?: number     // >= 768px
  lg?: number     // >= 1024px
  xl?: number     // >= 1280px
  xxl?: number    // >= 1536px
}

export interface VirtualGridProps<T> {
  items: T[]
  columns: ColumnConfig
  gap?: number              // gap in px (default 16 = gap-4)
  estimateHeight?: number   // estimated row height in px (default 280)
  renderItem: (item: T, index: number) => React.ReactNode
  onLoadMore?: () => void
  hasMore?: boolean
  isLoading?: boolean
  loadingElement?: React.ReactNode
  overscan?: number         // extra rows to render (default 3)
  className?: string
  focusedIndex?: number | null
  onScrollToIndex?: (index: number) => void
  onColCountChange?: (count: number) => void
}

function getColumnCount(width: number, config: ColumnConfig): number {
  if (config.xxl !== undefined && width >= 1536) return config.xxl
  if (config.xl !== undefined && width >= 1280) return config.xl
  if (config.lg !== undefined && width >= 1024) return config.lg
  if (config.md !== undefined && width >= 768) return config.md
  if (config.sm !== undefined && width >= 640) return config.sm
  return config.base
}

export function VirtualGrid<T>({
  items,
  columns,
  gap = 16,
  estimateHeight = 280,
  renderItem,
  onLoadMore,
  hasMore = false,
  isLoading = false,
  loadingElement,
  overscan = 3,
  className,
  focusedIndex,
  onColCountChange,
}: VirtualGridProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [scrollMargin, setScrollMargin] = useState(0)
  const prevScrollMarginRef = useRef(0)
  const [colCount, setColCount] = useState<number>(() => {
    if (typeof window === 'undefined') return columns.base
    return getColumnCount(window.innerWidth, columns)
  })

  // Stable key for the columns config (avoids effect re-run on every render when columns is an inline object)
  const columnsKey = JSON.stringify(columns)

  // Keep onColCountChange in a ref so the ResizeObserver effect doesn't need it as a dependency
  const onColCountChangeRef = useRef(onColCountChange)
  useEffect(() => {
    onColCountChangeRef.current = onColCountChange
  }, [onColCountChange])

  // ResizeObserver on the container to detect width changes and keep scrollMargin up to date
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    // Set initial scrollMargin (guarded to skip redundant state update)
    const initialMargin = el.offsetTop
    if (initialMargin !== prevScrollMarginRef.current) {
      prevScrollMarginRef.current = initialMargin
      setScrollMargin(initialMargin)
    }

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const width = entry.contentRect.width
      const next = getColumnCount(width, columns)
      setColCount((prev) => {
        if (prev !== next) {
          onColCountChangeRef.current?.(next)
          return next
        }
        return prev
      })
      // Update scrollMargin in case content above the grid changed, only when value differs
      const newMargin = el.offsetTop
      if (newMargin !== prevScrollMarginRef.current) {
        prevScrollMarginRef.current = newMargin
        setScrollMargin(newMargin)
      }
    })

    ro.observe(el)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columnsKey])

  // Split flat items array into rows
  const rows = useMemo(() => {
    if (colCount <= 0 || items.length === 0) return []
    const result: T[][] = []
    for (let i = 0; i < items.length; i += colCount) {
      result.push(items.slice(i, i + colCount))
    }
    return result
  }, [items, colCount])

  const rowCount = rows.length

  const virtualizer = useWindowVirtualizer({
    count: rowCount,
    estimateSize: () => estimateHeight + gap,
    overscan,
    scrollMargin,
  })

  const virtualItems = virtualizer.getVirtualItems()

  // Keep a stable ref to the virtualizer so the scrollToIndex effect
  // doesn't need the virtualizer instance (which changes every render) as a dep
  const virtualizerRef = useRef(virtualizer)
  useEffect(() => {
    virtualizerRef.current = virtualizer
  })

  // Scroll virtualizer to ensure focusedIndex row is visible.
  // align:'auto' means no-op if the row is already fully visible.
  useEffect(() => {
    if (focusedIndex === null || focusedIndex === undefined) return
    const rowIndex = Math.floor(focusedIndex / colCount)
    virtualizerRef.current.scrollToIndex(rowIndex, { align: 'auto' })
  }, [focusedIndex, colCount])

  // Keep a ref to onLoadMore so the effect never needs it as a dependency
  const onLoadMoreRef = useRef(onLoadMore)
  useEffect(() => {
    onLoadMoreRef.current = onLoadMore
  }, [onLoadMore])

  // Prevent onLoadMore from firing repeatedly for the same item count.
  // Only allow re-firing after items.length actually grows (new data arrived).
  // Reset when items decrease (e.g. filter change resets the list).
  const loadMoreFiredAt = useRef(-1)
  const prevItemsLength = useRef(items.length)
  useEffect(() => {
    if (items.length < prevItemsLength.current) {
      loadMoreFiredAt.current = -1
    }
    prevItemsLength.current = items.length
  }, [items.length])

  // Trigger onLoadMore when the last virtual row enters the visible area
  const lastVirtualItem = virtualItems[virtualItems.length - 1]
  useEffect(() => {
    if (!lastVirtualItem) return
    if (!hasMore || isLoading) return
    if (loadMoreFiredAt.current >= items.length) return
    if (lastVirtualItem.index >= rowCount - 1) {
      loadMoreFiredAt.current = items.length
      onLoadMoreRef.current?.()
    }
  }, [lastVirtualItem, hasMore, isLoading, rowCount, items.length])

  if (items.length === 0) return null

  const totalHeight = virtualizer.getTotalSize()

  return (
    <div ref={containerRef} className={className}>
      {/* Virtual scroll container — height matches total virtual height */}
      <div
        style={{
          height: totalHeight,
          position: 'relative',
        }}
      >
        {virtualItems.map((virtualRow) => {
          const rowItems = rows[virtualRow.index]
          if (!rowItems) return null

          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                transform: `translateY(${virtualRow.start - virtualizer.options.scrollMargin}px)`,
                paddingBottom: gap,
              }}
            >
              {/* CSS grid row — same column count as the Tailwind equivalent */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: `repeat(${colCount}, minmax(0, 1fr))`,
                  gap: gap,
                }}
              >
                {rowItems.map((item, colIdx) => {
                  const globalIndex = virtualRow.index * colCount + colIdx
                  return (
                    <div
                      key={globalIndex}
                      data-grid-index={globalIndex}
                      tabIndex={-1}
                      className="rounded-lg outline-none focus:ring-2 focus:ring-vault-accent focus:ring-offset-1 focus:ring-offset-vault-bg"
                    >
                      {renderItem(item, globalIndex)}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {/* Loading / end indicator */}
      {(isLoading || hasMore) && (
        <div className="flex justify-center py-4">
          {isLoading ? (loadingElement ?? <LoadingSpinner />) : null}
        </div>
      )}
    </div>
  )
}
