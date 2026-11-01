'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

/** Pixels the pointer must travel before a press on empty space becomes a marquee. */
export const MARQUEE_DRAG_THRESHOLD = 4
/** Distance from the scroll container's top/bottom edge that triggers auto-scroll. */
export const MARQUEE_AUTOSCROLL_EDGE = 40
/** Maximum auto-scroll step per animation frame. */
export const MARQUEE_AUTOSCROLL_MAX_STEP = 24

const MARQUEE_IGNORE_SELECTOR = '[data-explorer-item], button, a, input, select, textarea, label, [role="menu"]'

export interface MarqueeRect {
  left: number
  top: number
  width: number
  height: number
}

export interface SelectionClickModifiers {
  shiftKey?: boolean
  ctrlKey?: boolean
  metaKey?: boolean
}

export interface UseExplorerSelectionOptions {
  /** Ordered keys of the items currently rendered (index order == visual order). */
  keys: readonly string[]
  /** The scrolling element that contains the items; marquee coordinates are relative to its content. */
  scrollRef: RefObject<HTMLElement | null>
  /** Marquee is fine-pointer only; pass `false` on coarse pointers. */
  marqueeEnabled?: boolean
  /** Coarse-pointer behavior: a plain click toggles the item instead of replacing the selection. */
  toggleOnClick?: boolean
  /** Fired once when a press on empty space turns into a real drag (selection is about to be replaced). */
  onMarqueeStart?: () => void
  /** Fired when a plain click on empty space clears the selection. */
  onBackgroundClick?: () => void
}

interface DragState {
  pointerId: number
  startX: number
  startY: number
  startClientX: number
  startClientY: number
  clientX: number
  clientY: number
  additive: boolean
  base: Set<string>
  started: boolean
  frame: number | null
  cleanup: () => void
}

function sameSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size !== b.size) return false
  for (const value of a) if (!b.has(value)) return false
  return true
}

/**
 * Selection shared by gallery cards and image tiles, with Windows Explorer
 * semantics: click selects one, Ctrl/Meta toggles, Shift selects a range from the
 * anchor, Ctrl+Shift adds a range, and dragging on empty space draws a marquee.
 */
export function useExplorerSelection({
  keys,
  scrollRef,
  marqueeEnabled = true,
  toggleOnClick = false,
  onMarqueeStart,
  onBackgroundClick,
}: UseExplorerSelectionOptions) {
  const [selectedKeys, setSelectedKeysState] = useState<Set<string>>(() => new Set())
  const [marquee, setMarquee] = useState<MarqueeRect | null>(null)
  const selectedRef = useRef(selectedKeys)
  const anchorRef = useRef<number | null>(null)
  const itemElementsRef = useRef(new Map<string, HTMLElement>())
  const dragRef = useRef<DragState | null>(null)
  const latestRef = useRef({ keys, marqueeEnabled, toggleOnClick, onMarqueeStart, onBackgroundClick })

  useLayoutEffect(() => {
    latestRef.current = { keys, marqueeEnabled, toggleOnClick, onMarqueeStart, onBackgroundClick }
  }, [keys, marqueeEnabled, toggleOnClick, onMarqueeStart, onBackgroundClick])

  const commit = useCallback((next: Set<string>) => {
    selectedRef.current = next
    setSelectedKeysState(next)
  }, [])

  const replace = useCallback((next: Iterable<string>) => commit(new Set(next)), [commit])

  const clear = useCallback(() => {
    anchorRef.current = null
    if (selectedRef.current.size > 0) commit(new Set())
  }, [commit])

  const selectAll = useCallback(() => {
    commit(new Set(latestRef.current.keys))
  }, [commit])

  const toggle = useCallback((index: number) => {
    const key = latestRef.current.keys[index]
    if (key === undefined) return
    const next = new Set(selectedRef.current)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    anchorRef.current = index
    commit(next)
  }, [commit])

  const selectOnly = useCallback((index: number) => {
    const key = latestRef.current.keys[index]
    if (key === undefined) return
    anchorRef.current = index
    commit(new Set([key]))
  }, [commit])

  /** Keyboard Shift+arrows: the selection becomes the range anchor..toIndex. */
  const extendTo = useCallback((fromIndex: number, toIndex: number) => {
    const all = latestRef.current.keys
    const anchor = anchorRef.current ?? fromIndex
    anchorRef.current = anchor
    const start = Math.max(0, Math.min(anchor, toIndex))
    const end = Math.min(all.length - 1, Math.max(anchor, toIndex))
    commit(new Set(all.slice(start, end + 1)))
  }, [commit])

  const onItemClick = useCallback((index: number, event?: SelectionClickModifiers) => {
    const { keys: all, toggleOnClick: toggleMode } = latestRef.current
    const key = all[index]
    if (key === undefined) return
    const additive = Boolean(event?.ctrlKey || event?.metaKey)
    const anchor = anchorRef.current
    if (event?.shiftKey && anchor !== null && anchor < all.length) {
      const range = all.slice(Math.min(anchor, index), Math.max(anchor, index) + 1)
      commit(additive ? new Set([...selectedRef.current, ...range]) : new Set(range))
      return
    }
    if (additive || toggleMode) {
      toggle(index)
      return
    }
    selectOnly(index)
  }, [commit, toggle, selectOnly])

  const registerItem = useCallback((key: string, element: HTMLElement | null) => {
    if (element) itemElementsRef.current.set(key, element)
    else itemElementsRef.current.delete(key)
  }, [])

  const onContainerPointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const { marqueeEnabled: enabled } = latestRef.current
    const scroller = scrollRef.current
    if (!enabled || !scroller || dragRef.current) return
    if (event.button !== 0) return
    if (event.pointerType && event.pointerType !== 'mouse') return
    if (!(event.target instanceof Element) || event.target.closest(MARQUEE_IGNORE_SELECTOR)) return
    const box = scroller.getBoundingClientRect()
    // A press on the scrollbar belongs to the scrollbar.
    if (scroller.clientWidth > 0 && event.clientX - box.left >= scroller.clientWidth) return
    if (scroller.clientHeight > 0 && event.clientY - box.top >= scroller.clientHeight) return

    const toContent = (clientX: number, clientY: number) => {
      const current = scroller.getBoundingClientRect()
      return {
        x: clientX - current.left - scroller.clientLeft + scroller.scrollLeft,
        y: clientY - current.top - scroller.clientTop + scroller.scrollTop,
      }
    }
    const origin = toContent(event.clientX, event.clientY)
    const previousUserSelect = document.body.style.userSelect

    const update = () => {
      const drag = dragRef.current
      if (!drag) return
      const point = toContent(drag.clientX, drag.clientY)
      const maxX = Math.max(scroller.scrollWidth, 0)
      const maxY = Math.max(scroller.scrollHeight, 0)
      const clampedX = Math.min(Math.max(point.x, 0), maxX)
      const clampedY = Math.min(Math.max(point.y, 0), maxY)
      const x1 = Math.min(drag.startX, clampedX)
      const x2 = Math.max(drag.startX, clampedX)
      const y1 = Math.min(drag.startY, clampedY)
      const y2 = Math.max(drag.startY, clampedY)
      setMarquee({ left: x1, top: y1, width: x2 - x1, height: y2 - y1 })

      const current = scroller.getBoundingClientRect()
      const offsetX = current.left + scroller.clientLeft - scroller.scrollLeft
      const offsetY = current.top + scroller.clientTop - scroller.scrollTop
      const next = new Set(drag.additive ? drag.base : [])
      for (const [key, element] of itemElementsRef.current) {
        const r = element.getBoundingClientRect()
        if (r.left - offsetX < x2 && r.right - offsetX > x1 && r.top - offsetY < y2 && r.bottom - offsetY > y1) next.add(key)
      }
      if (!sameSet(next, selectedRef.current)) commit(next)
    }

    const tick = () => {
      const drag = dragRef.current
      if (!drag) return
      drag.frame = null
      if (drag.started) {
        const current = scroller.getBoundingClientRect()
        let step = 0
        const fromTop = drag.clientY - current.top
        const fromBottom = current.bottom - drag.clientY
        if (fromTop < MARQUEE_AUTOSCROLL_EDGE) {
          step = -Math.min(MARQUEE_AUTOSCROLL_MAX_STEP, Math.ceil(((MARQUEE_AUTOSCROLL_EDGE - fromTop) / MARQUEE_AUTOSCROLL_EDGE) * MARQUEE_AUTOSCROLL_MAX_STEP))
        } else if (fromBottom < MARQUEE_AUTOSCROLL_EDGE) {
          step = Math.min(MARQUEE_AUTOSCROLL_MAX_STEP, Math.ceil(((MARQUEE_AUTOSCROLL_EDGE - fromBottom) / MARQUEE_AUTOSCROLL_EDGE) * MARQUEE_AUTOSCROLL_MAX_STEP))
        }
        if (step !== 0) {
          const before = scroller.scrollTop
          scroller.scrollTop = before + step
          if (scroller.scrollTop !== before) update()
        }
      }
      drag.frame = window.requestAnimationFrame(tick)
    }

    const onMove = (moveEvent: PointerEvent) => {
      const drag = dragRef.current
      if (!drag || moveEvent.pointerId !== drag.pointerId) return
      drag.clientX = moveEvent.clientX
      drag.clientY = moveEvent.clientY
      if (!drag.started) {
        if (Math.hypot(drag.clientX - drag.startClientX, drag.clientY - drag.startClientY) < MARQUEE_DRAG_THRESHOLD) return
        drag.started = true
        document.body.style.userSelect = 'none'
        window.getSelection()?.removeAllRanges()
        if (!drag.additive) {
          anchorRef.current = null
          drag.base = new Set()
        }
        latestRef.current.onMarqueeStart?.()
      }
      update()
    }

    const finish = (cancelled: boolean) => {
      const drag = dragRef.current
      if (!drag) return
      const wasDrag = drag.started
      drag.cleanup()
      dragRef.current = null
      setMarquee(null)
      if (!wasDrag && !cancelled && !drag.additive) {
        clear()
        latestRef.current.onBackgroundClick?.()
      }
    }

    const onUp = (upEvent: PointerEvent) => {
      if (upEvent.pointerId !== dragRef.current?.pointerId) return
      finish(false)
    }
    const onCancel = (cancelEvent: PointerEvent) => {
      if (cancelEvent.pointerId !== dragRef.current?.pointerId) return
      finish(true)
    }
    const onBlur = () => finish(true)

    const drag: DragState = {
      pointerId: event.pointerId,
      startX: origin.x,
      startY: origin.y,
      startClientX: event.clientX,
      startClientY: event.clientY,
      clientX: event.clientX,
      clientY: event.clientY,
      additive: event.ctrlKey || event.metaKey,
      base: new Set(selectedRef.current),
      started: false,
      frame: null,
      cleanup: () => {
        scroller.removeEventListener('pointermove', onMove)
        scroller.removeEventListener('pointerup', onUp)
        scroller.removeEventListener('pointercancel', onCancel)
        window.removeEventListener('blur', onBlur)
        if (drag.frame !== null) window.cancelAnimationFrame(drag.frame)
        document.body.style.userSelect = previousUserSelect
        try {
          scroller.releasePointerCapture?.(drag.pointerId)
        } catch {
          // The pointer may already be released.
        }
      },
    }
    dragRef.current = drag
    try {
      scroller.setPointerCapture?.(event.pointerId)
    } catch {
      // Synthetic or already-released pointers cannot be captured.
    }
    scroller.addEventListener('pointermove', onMove)
    scroller.addEventListener('pointerup', onUp)
    scroller.addEventListener('pointercancel', onCancel)
    window.addEventListener('blur', onBlur)
    drag.frame = window.requestAnimationFrame(tick)
  }, [clear, commit, scrollRef])

  useEffect(() => () => {
    dragRef.current?.cleanup()
    dragRef.current = null
  }, [])

  return {
    selectedKeys,
    isSelected: (key: string) => selectedKeys.has(key),
    marquee,
    onContainerPointerDown,
    onItemClick,
    toggle,
    selectOnly,
    extendTo,
    selectAll,
    clear,
    replace,
    registerItem,
  }
}
