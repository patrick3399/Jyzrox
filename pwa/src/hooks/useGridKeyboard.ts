'use client'

import { useState, useEffect, useRef, useCallback } from 'react'

interface UseGridKeyboardOptions {
  totalItems: number
  colCount: number
  onEnter: (index: number) => void
  enabled?: boolean
  restoreFocusedIndex?: number | null
}

export function useGridKeyboard({
  totalItems,
  colCount,
  onEnter,
  enabled = true,
  restoreFocusedIndex = null,
}: UseGridKeyboardOptions) {
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null)
  const elementMapRef = useRef(new Map<number, HTMLElement>())
  const previousTotalItemsRef = useRef(totalItems)
  const appliedRestoreIndexRef = useRef<number | null>(null)

  const findVisibleIndex = useCallback((backward: boolean): number | null => {
    const visibleIndexes = Array.from(elementMapRef.current.entries())
      .filter(([, element]) => {
        const rect = element.getBoundingClientRect()
        return rect.bottom > 0 && rect.top < window.innerHeight
      })
      .map(([index]) => index)
      .sort((a, b) => a - b)

    if (visibleIndexes.length === 0) return null
    return backward ? visibleIndexes[visibleIndexes.length - 1] : visibleIndexes[0]
  }, [])

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
        if (prev === null) {
          const visibleIndex = findVisibleIndex(e.key === 'ArrowLeft' || e.key === 'ArrowUp')
          if (visibleIndex !== null) return visibleIndex
        }
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
  }, [enabled, totalItems, colCount, onEnter, findVisibleIndex])

  const registerElement = useCallback((index: number, el: HTMLElement | null) => {
    if (el) {
      elementMapRef.current.set(index, el)
    } else {
      elementMapRef.current.delete(index)
    }
  }, [])

  // The Library route saves the exact gallery identity before keyboard Enter.
  // Its pages may hydrate after this hook mounts, so apply the resolved index
  // once it becomes available instead of approximating from the viewport edge.
  useEffect(() => {
    if (restoreFocusedIndex === null || restoreFocusedIndex < 0) return
    if (appliedRestoreIndexRef.current === restoreFocusedIndex) return
    appliedRestoreIndexRef.current = restoreFocusedIndex
    setFocusedIndex(restoreFocusedIndex)
  }, [restoreFocusedIndex])

  // Focus the grid item wrapper (has tabIndex={-1}) so the ring appears.
  useEffect(() => {
    if (focusedIndex === null) return
    const el = elementMapRef.current.get(focusedIndex)
    el?.focus({ preventScroll: true })
  }, [focusedIndex])

  // A growing item count is an infinite-scroll append, so keep the current
  // keyboard position. Reset only when the list shrinks (filter/query change);
  // otherwise the next held ArrowDown starts again at index 0 and makes the
  // window virtualizer jump back to the top.
  useEffect(() => {
    if (totalItems < previousTotalItemsRef.current) {
      setFocusedIndex(null)
    }
    previousTotalItemsRef.current = totalItems
  }, [totalItems])

  return { focusedIndex, registerElement }
}
