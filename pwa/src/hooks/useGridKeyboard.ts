'use client'

import { useState, useEffect } from 'react'

interface UseGridKeyboardOptions {
  totalItems: number
  colCount: number
  onEnter: (index: number) => void
  enabled?: boolean
}

export function useGridKeyboard({
  totalItems,
  colCount,
  onEnter,
  enabled = true,
}: UseGridKeyboardOptions) {
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null)

  useEffect(() => {
    if (!enabled) return

    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

      // Call preventDefault BEFORE setFocusedIndex — updater runs asynchronously
      // and by then the event is already processed, making preventDefault a no-op.
      switch (e.key) {
        case 'ArrowRight':
        case 'ArrowLeft':
        case 'ArrowDown':
          e.preventDefault()
          break
        case 'ArrowUp':
          e.preventDefault()
          break
        case 'Enter': {
          // Let the browser handle Enter on focused <a>/<button> natively;
          // also call onEnter for programmatic navigation.
          setFocusedIndex((prev) => {
            if (prev !== null && prev >= 0 && prev < totalItems) {
              onEnter(prev)
            }
            return prev
          })
          return
        }
        case 'Escape':
          setFocusedIndex(null)
          return
        default:
          return
      }

      // Now update focusedIndex after preventDefault
      setFocusedIndex((prev) => {
        const current = prev ?? -1
        switch (e.key) {
          case 'ArrowRight':
            return Math.min(current + 1, totalItems - 1)
          case 'ArrowLeft':
            return current <= 0 ? 0 : Math.max(current - 1, 0)
          case 'ArrowDown':
            if (current === -1) return 0
            return Math.min(current + colCount, totalItems - 1)
          case 'ArrowUp': {
            if (current <= 0) return prev
            const next = current - colCount
            return next >= 0 ? next : prev
          }
          default:
            return prev
        }
      })
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [enabled, totalItems, colCount, onEnter])

  // Focus the grid item wrapper (has tabIndex={-1}) so the ring appears.
  useEffect(() => {
    if (focusedIndex === null) return
    const el = document.querySelector(`[data-grid-index="${focusedIndex}"]`) as HTMLElement | null
    el?.focus({ preventScroll: true })
  }, [focusedIndex])

  // Reset when item count changes (filter / page change)
  useEffect(() => {
    setFocusedIndex(null)
  }, [totalItems])

  return { focusedIndex }
}
