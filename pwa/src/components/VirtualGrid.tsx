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
}

function getColumnCount(width: number, config: ColumnConfig): number {
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
}: VirtualGridProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [colCount, setColCount] = useState<number>(() => {
    if (typeof window === 'undefined') return columns.base
    return getColumnCount(window.innerWidth, columns)
  })

  // ResizeObserver on the container to detect width changes
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const width = entry.contentRect.width
      const next = getColumnCount(width, columns)
      setColCount((prev) => (prev !== next ? next : prev))
    })

    ro.observe(el)
    return () => ro.disconnect()
  }, [columns])

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
    scrollMargin: containerRef.current?.offsetTop ?? 0,
  })

  const virtualItems = virtualizer.getVirtualItems()

  // Trigger onLoadMore when the last virtual row enters the visible area
  const lastVirtualItem = virtualItems[virtualItems.length - 1]
  const onLoadMoreRef = useRef(onLoadMore)
  onLoadMoreRef.current = onLoadMore

  useEffect(() => {
    if (!lastVirtualItem) return
    if (!hasMore || isLoading) return
    if (lastVirtualItem.index >= rowCount - 1) {
      onLoadMoreRef.current?.()
    }
  }, [lastVirtualItem?.index, hasMore, isLoading, rowCount])

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
                    <div key={globalIndex}>
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
