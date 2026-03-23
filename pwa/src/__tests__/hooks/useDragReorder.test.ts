/**
 * useDragReorder hook — Vitest test suite
 *
 * Covers:
 *   Initial state: dragIdx and dragOver are null
 *   getDragProps returns object with draggable: true and correct data-drag-index
 *   getDragProps returns style with touchAction: 'none'
 *   HTML5 drag: dragStart sets dragIdx, dragEnd with different dragOver calls onReorder
 *   HTML5 drag: dragEnd with same index does NOT call onReorder
 *   HTML5 drag: reorder moves item from index 0 to 2 correctly (['a','b','c'] → ['b','c','a'])
 *   getDragProps onDragOver calls preventDefault
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useDragReorder } from '@/hooks/useDragReorder'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useDragReorder — initial state', () => {
  it('test_useDragReorder_initialState_dragIdxIsNull', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    expect(result.current.dragIdx).toBeNull()
  })

  it('test_useDragReorder_initialState_dragOverIsNull', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    expect(result.current.dragOver).toBeNull()
  })
})

describe('useDragReorder — getDragProps shape', () => {
  it('test_useDragReorder_getDragProps_returnsDraggableTrue', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    const props = result.current.getDragProps(1)
    expect(props.draggable).toBe(true)
  })

  it('test_useDragReorder_getDragProps_returnsCorrectDataDragIndex', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    const props = result.current.getDragProps(2)
    expect(props['data-drag-index']).toBe(2)
  })

  it('test_useDragReorder_getDragProps_styleHasTouchActionNone', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    const props = result.current.getDragProps(0)
    expect(props.style).toEqual({ touchAction: 'none' })
  })

  it('test_useDragReorder_onDragOver_callsPreventDefault', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    const props = result.current.getDragProps(0)
    const mockEvent = { preventDefault: vi.fn() } as unknown as React.DragEvent
    props.onDragOver(mockEvent)
    expect(mockEvent.preventDefault).toHaveBeenCalled()
  })
})

describe('useDragReorder — HTML5 drag reordering', () => {
  it('test_useDragReorder_dragStart_setsDragIdx', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    act(() => {
      result.current.getDragProps(1).onDragStart()
    })
    expect(result.current.dragIdx).toBe(1)
  })

  it('test_useDragReorder_dragEnd_differentIndex_callsOnReorder', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    act(() => {
      result.current.getDragProps(0).onDragStart()
      result.current.getDragProps(2).onDragEnter()
      result.current.getDragProps(0).onDragEnd()
    })
    expect(onReorder).toHaveBeenCalledOnce()
  })

  it('test_useDragReorder_dragEnd_sameIndex_doesNotCallOnReorder', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    act(() => {
      result.current.getDragProps(1).onDragStart()
      result.current.getDragProps(1).onDragEnter()
      result.current.getDragProps(1).onDragEnd()
    })
    expect(onReorder).not.toHaveBeenCalled()
  })

  it('test_useDragReorder_dragReorder_index0To2_movesItemCorrectly', () => {
    const onReorder = vi.fn()
    const items = ['a', 'b', 'c']
    const { result } = renderHook(() =>
      useDragReorder({ items, onReorder }),
    )
    act(() => {
      result.current.getDragProps(0).onDragStart()
      result.current.getDragProps(2).onDragEnter()
      result.current.getDragProps(0).onDragEnd()
    })
    expect(onReorder).toHaveBeenCalledWith(['b', 'c', 'a'])
  })

  it('test_useDragReorder_dragEnd_resetsStateToNull', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragReorder({ items: ['a', 'b', 'c'], onReorder }),
    )
    act(() => {
      result.current.getDragProps(0).onDragStart()
      result.current.getDragProps(2).onDragEnter()
      result.current.getDragProps(0).onDragEnd()
    })
    expect(result.current.dragIdx).toBeNull()
    expect(result.current.dragOver).toBeNull()
  })
})
