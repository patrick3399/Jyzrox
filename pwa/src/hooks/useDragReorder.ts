import { useState, useCallback, useRef } from 'react'

interface UseDragReorderOptions {
  items: string[]
  onReorder: (newItems: string[]) => void
}

interface DragProps {
  draggable: true
  'data-drag-index': number
  style: { touchAction: 'none' }
  onDragStart: () => void
  onDragEnter: () => void
  onDragEnd: () => void
  onDragOver: (e: React.DragEvent) => void
  onTouchStart: (e: React.TouchEvent) => void
  onTouchMove: (e: React.TouchEvent) => void
  onTouchEnd: () => void
}

interface UseDragReorderResult {
  dragIdx: number | null
  dragOver: number | null
  getDragProps: (idx: number) => DragProps
}

const TOUCH_THRESHOLD = 5

export function useDragReorder({ items, onReorder }: UseDragReorderOptions): UseDragReorderResult {
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)

  // Refs to keep callbacks stable — avoids cascade recreation
  const itemsRef = useRef(items)
  itemsRef.current = items
  const onReorderRef = useRef(onReorder)
  onReorderRef.current = onReorder
  const dragIdxRef = useRef<number | null>(null)
  const dragOverRef = useRef<number | null>(null)

  // Touch-specific refs
  const touchStartIdx = useRef<number | undefined>(undefined)
  const touchStartY = useRef<number | undefined>(undefined)
  const touchCurrentOver = useRef<number | undefined>(undefined)
  const touchDidMove = useRef<boolean>(false)

  const commitReorder = useCallback((fromIdx: number, toIdx: number) => {
    if (fromIdx === toIdx) return
    const next = [...itemsRef.current]
    const [moved] = next.splice(fromIdx, 1)
    next.splice(toIdx, 0, moved)
    onReorderRef.current(next)
  }, [])

  // HTML5 drag handlers — stable via refs
  const handleDragEnd = useCallback(() => {
    const from = dragIdxRef.current
    const to = dragOverRef.current
    if (from !== null && to !== null && from !== to) {
      commitReorder(from, to)
    }
    dragIdxRef.current = null
    dragOverRef.current = null
    setDragIdx(null)
    setDragOver(null)
  }, [commitReorder])

  const handleDragStart = useCallback((idx: number) => {
    dragIdxRef.current = idx
    setDragIdx(idx)
  }, [])

  const handleDragEnter = useCallback((idx: number) => {
    dragOverRef.current = idx
    setDragOver(idx)
  }, [])

  // Touch handlers
  const handleTouchStart = useCallback((idx: number, e: React.TouchEvent) => {
    touchStartIdx.current = idx
    touchStartY.current = e.touches[0].clientY
    touchCurrentOver.current = idx
    touchDidMove.current = false
    dragIdxRef.current = idx
    setDragIdx(idx)
  }, [])

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (touchStartIdx.current === undefined || touchStartY.current === undefined) return

    const touch = e.touches[0]
    const deltaY = Math.abs(touch.clientY - touchStartY.current)

    if (deltaY >= TOUCH_THRESHOLD) {
      touchDidMove.current = true
    }

    if (!touchDidMove.current) return

    // Find which drag item the finger is currently over
    const el = document.elementFromPoint(touch.clientX, touch.clientY)
    if (!el) return

    const target = el.closest('[data-drag-index]') as HTMLElement | null
    if (!target) return

    const idxAttr = target.getAttribute('data-drag-index')
    if (idxAttr === null) return

    const overIdx = parseInt(idxAttr, 10)
    if (!isNaN(overIdx) && overIdx !== touchCurrentOver.current) {
      touchCurrentOver.current = overIdx
      dragOverRef.current = overIdx
      setDragOver(overIdx)
    }
  }, [])

  const handleTouchEnd = useCallback(() => {
    const fromIdx = touchStartIdx.current
    const toIdx = touchCurrentOver.current

    if (touchDidMove.current && fromIdx !== undefined && toIdx !== undefined && fromIdx !== toIdx) {
      commitReorder(fromIdx, toIdx)
    }

    touchStartIdx.current = undefined
    touchStartY.current = undefined
    touchCurrentOver.current = undefined
    touchDidMove.current = false
    dragIdxRef.current = null
    dragOverRef.current = null
    setDragIdx(null)
    setDragOver(null)
  }, [commitReorder])

  // Stable — all handler deps are stable useCallbacks with [] deps
  const getDragProps = useCallback(
    (idx: number): DragProps => ({
      draggable: true,
      'data-drag-index': idx,
      style: { touchAction: 'none' },
      onDragStart: () => handleDragStart(idx),
      onDragEnter: () => handleDragEnter(idx),
      onDragEnd: handleDragEnd,
      onDragOver: (e: React.DragEvent) => e.preventDefault(),
      onTouchStart: (e: React.TouchEvent) => handleTouchStart(idx, e),
      onTouchMove: handleTouchMove,
      onTouchEnd: handleTouchEnd,
    }),
    [
      handleDragEnd,
      handleDragStart,
      handleDragEnter,
      handleTouchStart,
      handleTouchMove,
      handleTouchEnd,
    ],
  )

  return { dragIdx, dragOver, getDragProps }
}
