/**
 * useGridKeyboard — Vitest test suite
 *
 * Covers:
 *   Initial state    — focusedIndex starts as null
 *   ArrowRight       — from null starts at 0; increments index; clamps at last item
 *   ArrowDown        — moves forward by colCount
 *   ArrowUp          — moves backward by colCount; does not go below 0
 *   Enter            — calls onEnter with the current focusedIndex
 *   Escape           — resets focusedIndex to null
 *   enabled=false    — keydowns are ignored entirely
 *   totalItems reset — focusedIndex resets to null when totalItems changes
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function simulateKeydown(key: string): void {
  const event = new KeyboardEvent('keydown', { key, bubbles: true })
  window.dispatchEvent(event)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useGridKeyboard', () => {
  let onEnter: ReturnType<typeof vi.fn<(index: number) => void>>

  beforeEach(() => {
    onEnter = vi.fn<(index: number) => void>()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('test_useGridKeyboard_initial_state_focusedIndex_is_null', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter }),
    )

    expect(result.current.focusedIndex).toBeNull()
  })

  it('test_useGridKeyboard_arrowRight_from_null_starts_at_index_0', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter }),
    )

    act(() => {
      simulateKeydown('ArrowRight')
    })

    expect(result.current.focusedIndex).toBe(0)
  })

  it('test_useGridKeyboard_arrowRight_increments_focused_index', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter }),
    )

    // Navigate to index 0 first
    act(() => {
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(0)

    // Then advance to 1
    act(() => {
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(1)
  })

  it('test_useGridKeyboard_arrowRight_at_last_item_stays_at_last_item', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 3, colCount: 3, onEnter }),
    )

    // Navigate to index 2 (last)
    act(() => {
      simulateKeydown('ArrowRight')
      simulateKeydown('ArrowRight')
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(2)

    // One more ArrowRight should clamp at 2
    act(() => {
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(2)
  })

  it('test_useGridKeyboard_arrowDown_moves_by_colCount', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter }),
    )

    // Navigate to index 1 (null → 0 → 1)
    act(() => {
      simulateKeydown('ArrowRight')
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(1)

    // ArrowDown from 1 with colCount=3 → 4
    act(() => {
      simulateKeydown('ArrowDown')
    })
    expect(result.current.focusedIndex).toBe(4)
  })

  it('test_useGridKeyboard_arrowUp_moves_by_negative_colCount', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter }),
    )

    // Navigate to index 4
    act(() => {
      simulateKeydown('ArrowRight') // 0
      simulateKeydown('ArrowRight') // 1
      simulateKeydown('ArrowDown')  // 4
    })
    expect(result.current.focusedIndex).toBe(4)

    // ArrowUp from 4 with colCount=3 → 1
    act(() => {
      simulateKeydown('ArrowUp')
    })
    expect(result.current.focusedIndex).toBe(1)
  })

  it('test_useGridKeyboard_enter_calls_onEnter_with_current_index', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter }),
    )

    // Navigate to index 2
    act(() => {
      simulateKeydown('ArrowRight')
      simulateKeydown('ArrowRight')
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(2)

    act(() => {
      simulateKeydown('Enter')
    })

    expect(onEnter).toHaveBeenCalledOnce()
    expect(onEnter).toHaveBeenCalledWith(2)
  })

  it('test_useGridKeyboard_escape_resets_focusedIndex_to_null', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter }),
    )

    // Navigate somewhere
    act(() => {
      simulateKeydown('ArrowRight')
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(1)

    act(() => {
      simulateKeydown('Escape')
    })
    expect(result.current.focusedIndex).toBeNull()
  })

  it('test_useGridKeyboard_disabled_ignores_all_keydowns', () => {
    const { result } = renderHook(() =>
      useGridKeyboard({ totalItems: 9, colCount: 3, onEnter, enabled: false }),
    )

    act(() => {
      simulateKeydown('ArrowRight')
      simulateKeydown('ArrowDown')
      simulateKeydown('Enter')
    })

    expect(result.current.focusedIndex).toBeNull()
    expect(onEnter).not.toHaveBeenCalled()
  })

  it('test_useGridKeyboard_totalItems_change_resets_focusedIndex_to_null', () => {
    let totalItems = 9
    const { result, rerender } = renderHook(() =>
      useGridKeyboard({ totalItems, colCount: 3, onEnter }),
    )

    act(() => {
      simulateKeydown('ArrowRight')
    })
    expect(result.current.focusedIndex).toBe(0)

    // Simulate a filter change — totalItems shrinks
    totalItems = 3
    act(() => {
      rerender()
    })

    expect(result.current.focusedIndex).toBeNull()
  })
})
