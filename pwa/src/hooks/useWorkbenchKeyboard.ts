'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

interface WorkbenchKeyboardOptions {
  itemCount: number
  columnCount: number
  listMode: boolean
  enabled?: boolean
  onOpen: (index: number) => void
  onToggleSelection: (index: number) => void
  onExtendSelection: (fromIndex: number, toIndex: number) => void
  onSelectAll: () => void
  onClearSelection: () => boolean
  onBack: () => void
  onFocusSearch: () => void
  onDelete: () => void
  onEditMetadata: () => void
  onTreeLayout: () => void
  onColumnLayout: () => void
  onGridView: () => void
  onListView: () => void
  onShowShortcuts: () => void
  onCyclePane: () => void
}

function isTypingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
    Boolean(target.closest('[role="dialog"]'))
  )
}

function shouldIgnoreContentShortcut(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  if (isTypingTarget(target)) return true
  if (target.closest('[data-explorer-navigation]')) return true
  const item = target.closest<HTMLElement>('[data-explorer-item]')
  if (!item && target.closest('button, a, [role="button"]')) return true
  if (item && target !== item && target.closest('button, a, input, select, textarea')) return true
  return false
}

export function useWorkbenchKeyboard({
  itemCount,
  columnCount,
  listMode,
  enabled = true,
  onOpen,
  onToggleSelection,
  onExtendSelection,
  onSelectAll,
  onClearSelection,
  onBack,
  onFocusSearch,
  onDelete,
  onEditMetadata,
  onTreeLayout,
  onColumnLayout,
  onGridView,
  onListView,
  onShowShortcuts,
  onCyclePane,
}: WorkbenchKeyboardOptions) {
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null)
  const elementMapRef = useRef(new Map<number, HTMLElement>())
  const callbacksRef = useRef({
    onOpen,
    onToggleSelection,
    onExtendSelection,
    onSelectAll,
    onClearSelection,
    onBack,
    onFocusSearch,
    onDelete,
    onEditMetadata,
    onTreeLayout,
    onColumnLayout,
    onGridView,
    onListView,
    onShowShortcuts,
    onCyclePane,
  })

  useEffect(() => {
    callbacksRef.current = {
      onOpen,
      onToggleSelection,
      onExtendSelection,
      onSelectAll,
      onClearSelection,
      onBack,
      onFocusSearch,
      onDelete,
      onEditMetadata,
      onTreeLayout,
      onColumnLayout,
      onGridView,
      onListView,
      onShowShortcuts,
      onCyclePane,
    }
  }, [
    onOpen,
    onToggleSelection,
    onExtendSelection,
    onSelectAll,
    onClearSelection,
    onBack,
    onFocusSearch,
    onDelete,
    onEditMetadata,
    onTreeLayout,
    onColumnLayout,
    onGridView,
    onListView,
    onShowShortcuts,
    onCyclePane,
  ])

  const registerElement = useCallback((index: number, element: HTMLElement | null) => {
    if (element) elementMapRef.current.set(index, element)
    else elementMapRef.current.delete(index)
  }, [])

  const focusIndex = useCallback(
    (index: number | null) => {
      if (index === null || itemCount === 0) {
        setFocusedIndex(null)
        return
      }
      setFocusedIndex(Math.max(0, Math.min(index, itemCount - 1)))
    },
    [itemCount],
  )

  useEffect(() => {
    if (focusedIndex === null) return
    const element = elementMapRef.current.get(focusedIndex)
    element?.focus({ preventScroll: true })
    element?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [focusedIndex])

  useEffect(() => {
    setFocusedIndex((current) => {
      if (itemCount === 0) return null
      if (current === null) return null
      return Math.min(current, itemCount - 1)
    })
  }, [itemCount])

  useEffect(() => {
    if (!enabled) return

    const handler = (event: KeyboardEvent) => {
      if (event.isComposing || isTypingTarget(event.target)) return

      const callbacks = callbacksRef.current
      const commandKey = event.ctrlKey || event.metaKey

      if (commandKey && event.key.toLowerCase() === 'a') {
        event.preventDefault()
        callbacks.onSelectAll()
        return
      }
      if ((event.key === '/' && !commandKey && !event.altKey) || (commandKey && event.key.toLowerCase() === 'k')) {
        event.preventDefault()
        callbacks.onFocusSearch()
        return
      }
      if (event.key === '?' && !commandKey && !event.altKey) {
        event.preventDefault()
        callbacks.onShowShortcuts()
        return
      }
      if (event.key === 'F6') {
        event.preventDefault()
        callbacks.onCyclePane()
        return
      }
      if (event.altKey && event.key === '1') {
        event.preventDefault()
        callbacks.onTreeLayout()
        return
      }
      if (event.altKey && event.key === '2') {
        event.preventDefault()
        callbacks.onColumnLayout()
        return
      }
      if (commandKey && event.key === '1') {
        event.preventDefault()
        callbacks.onGridView()
        return
      }
      if (commandKey && event.key === '2') {
        event.preventDefault()
        callbacks.onListView()
        return
      }
      if (commandKey && event.key === 'Backspace') {
        event.preventDefault()
        callbacks.onDelete()
        return
      }
      if (event.key === 'Backspace' && !commandKey && !event.altKey) {
        event.preventDefault()
        callbacks.onBack()
        return
      }
      if (event.key === 'Delete') {
        event.preventDefault()
        callbacks.onDelete()
        return
      }
      if (event.key === 'F2') {
        event.preventDefault()
        callbacks.onEditMetadata()
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        if (!callbacks.onClearSelection()) setFocusedIndex(null)
        return
      }

      // Navigation panes own their arrows and activation keys, while the
      // workbench-wide management shortcuts above remain available anywhere.
      if (shouldIgnoreContentShortcut(event.target)) return

      if (event.key === 'Enter') {
        if (focusedIndex !== null) {
          event.preventDefault()
          callbacks.onOpen(focusedIndex)
        }
        return
      }
      if (event.key === ' ') {
        if (focusedIndex !== null) {
          event.preventDefault()
          callbacks.onToggleSelection(focusedIndex)
        }
        return
      }

      const isArrow = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)
      if (!isArrow || itemCount === 0) return

      if (listMode && event.key === 'ArrowLeft') {
        event.preventDefault()
        callbacks.onBack()
        return
      }
      if (listMode && event.key === 'ArrowRight') {
        if (focusedIndex !== null) {
          event.preventDefault()
          callbacks.onOpen(focusedIndex)
        }
        return
      }

      event.preventDefault()
      const previous = focusedIndex ?? 0
      let next = focusedIndex === null ? (event.key === 'End' ? itemCount - 1 : 0) : previous
      const columns = Math.max(1, columnCount)
      if (focusedIndex !== null) switch (event.key) {
        case 'ArrowLeft':
          next = Math.max(0, previous - 1)
          break
        case 'ArrowRight':
          next = Math.min(itemCount - 1, previous + 1)
          break
        case 'ArrowUp':
          next = Math.max(0, previous - columns)
          break
        case 'ArrowDown':
          next = Math.min(itemCount - 1, previous + columns)
          break
        case 'Home':
          next = 0
          break
        case 'End':
          next = itemCount - 1
          break
      }
      setFocusedIndex(next)
      if (event.shiftKey) callbacks.onExtendSelection(previous, next)
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [columnCount, enabled, focusedIndex, itemCount, listMode])

  return { focusedIndex, focusIndex, registerElement }
}
