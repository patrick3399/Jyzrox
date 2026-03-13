'use client'

import { useRef, useEffect, useState, useMemo, type ReactNode } from 'react'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import justifiedLayout from 'justified-layout'
import { LoadingSpinner } from '@/components/LoadingSpinner'

export interface JustifiedGridProps<T> {
  items: T[]
  getAspectRatio: (item: T) => number
  containerWidth: number
  targetRowHeight?: number
  boxSpacing?: number
  renderItem: (item: T, geometry: { width: number; height: number }) => ReactNode
  onLoadMore?: () => void
  hasMore?: boolean
  isLoading?: boolean
}

interface RowData<T> {
  top: number
  height: number
  items: Array<{ item: T; left: number; width: number; height: number }>
}

export function JustifiedGrid<T>({
  items,
  getAspectRatio,
  containerWidth,
  targetRowHeight = 240,
  boxSpacing = 4,
  renderItem,
  onLoadMore,
  hasMore = false,
  isLoading = false,
}: JustifiedGridProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [scrollMargin, setScrollMargin] = useState(0)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    setScrollMargin(el.offsetTop)
    const ro = new ResizeObserver(() => {
      setScrollMargin(el.offsetTop)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Compute layout
  const { rows, totalHeight } = useMemo(() => {
    if (!containerWidth || items.length === 0) return { rows: [] as RowData<T>[], totalHeight: 0 }

    const ratios = items.map((item) => {
      const r = getAspectRatio(item)
      return r > 0 && isFinite(r) ? r : 1
    })

    const layout = justifiedLayout(ratios, {
      containerWidth,
      targetRowHeight,
      boxSpacing: { horizontal: boxSpacing, vertical: boxSpacing },
      containerPadding: 0,
    })

    // Group boxes into rows by matching top values
    const rowMap = new Map<number, RowData<T>>()
    layout.boxes.forEach((box: { top: number; left: number; width: number; height: number }, idx: number) => {
      const roundedTop = Math.round(box.top)
      if (!rowMap.has(roundedTop)) {
        rowMap.set(roundedTop, { top: roundedTop, height: Math.round(box.height), items: [] })
      }
      rowMap.get(roundedTop)!.items.push({
        item: items[idx],
        left: Math.round(box.left),
        width: Math.round(box.width),
        height: Math.round(box.height),
      })
    })

    const sortedRows = Array.from(rowMap.values()).sort((a, b) => a.top - b.top)
    return { rows: sortedRows, totalHeight: Math.ceil(layout.containerHeight) }
  }, [items, containerWidth, targetRowHeight, boxSpacing, getAspectRatio])

  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: (i) => rows[i]?.height + boxSpacing || targetRowHeight,
    overscan: 3,
    scrollMargin,
  })

  const virtualItems = virtualizer.getVirtualItems()

  // Load more trigger
  const onLoadMoreRef = useRef(onLoadMore)
  useEffect(() => { onLoadMoreRef.current = onLoadMore }, [onLoadMore])
  const loadMoreFiredRef = useRef(-1)

  const lastVirtualItem = virtualItems[virtualItems.length - 1]
  useEffect(() => {
    if (!lastVirtualItem) return
    if (!hasMore || isLoading) return
    if (loadMoreFiredRef.current >= items.length) return
    if (lastVirtualItem.index >= rows.length - 1) {
      loadMoreFiredRef.current = items.length
      onLoadMoreRef.current?.()
    }
  }, [lastVirtualItem, hasMore, isLoading, rows.length, items.length])

  // Reset loadMore guard only when items shrink (filter change)
  const prevItemsLenRef = useRef(items.length)
  useEffect(() => {
    if (items.length < prevItemsLenRef.current) {
      loadMoreFiredRef.current = -1
    }
    prevItemsLenRef.current = items.length
  }, [items.length])

  if (items.length === 0) return <div ref={containerRef} />

  return (
    <div ref={containerRef} style={{ contain: 'layout style' }}>
      <div style={{ height: totalHeight, position: 'relative' }}>
        {virtualItems.map((virtualRow) => {
          const row = rows[virtualRow.index]
          if (!row) return null
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
                height: row.height + boxSpacing,
                contain: 'layout style paint',
              }}
            >
              {row.items.map((cell, i) => (
                <div
                  key={i}
                  style={{
                    position: 'absolute',
                    left: cell.left,
                    width: cell.width,
                    height: cell.height,
                  }}
                >
                  {renderItem(cell.item, { width: cell.width, height: cell.height })}
                </div>
              ))}
            </div>
          )
        })}
      </div>
      {(isLoading || hasMore) && (
        <div className="flex justify-center py-4">
          {isLoading ? <LoadingSpinner /> : null}
        </div>
      )}
    </div>
  )
}
