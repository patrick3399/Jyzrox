import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkbenchKeyboard } from '@/hooks/useWorkbenchKeyboard'

function press(key: string, init: KeyboardEventInit = {}) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...init }))
}

describe('useWorkbenchKeyboard', () => {
  const callbacks = {
    onOpen: vi.fn(),
    onToggleSelection: vi.fn(),
    onExtendSelection: vi.fn(),
    onSelectAll: vi.fn(),
    onClearSelection: vi.fn(() => false),
    onBack: vi.fn(),
    onFocusSearch: vi.fn(),
    onDelete: vi.fn(),
    onEditMetadata: vi.fn(),
    onTreeLayout: vi.fn(),
    onColumnLayout: vi.fn(),
    onGridView: vi.fn(),
    onListView: vi.fn(),
    onShowShortcuts: vi.fn(),
    onCyclePane: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    callbacks.onClearSelection.mockReturnValue(false)
  })

  function renderKeyboard(overrides: Partial<Parameters<typeof useWorkbenchKeyboard>[0]> = {}) {
    return renderHook(() => useWorkbenchKeyboard({
      itemCount: 12,
      columnCount: 3,
      listMode: false,
      ...callbacks,
      ...overrides,
    }))
  }

  it('moves grid focus with arrows, Home, and End', () => {
    const { result } = renderKeyboard()

    act(() => press('ArrowRight'))
    expect(result.current.focusedIndex).toBe(0)
    act(() => press('ArrowRight'))
    expect(result.current.focusedIndex).toBe(1)
    act(() => press('ArrowDown'))
    expect(result.current.focusedIndex).toBe(4)
    act(() => press('End'))
    expect(result.current.focusedIndex).toBe(11)
    act(() => press('Home'))
    expect(result.current.focusedIndex).toBe(0)
  })

  it('opens with Enter and toggles selection with Space', () => {
    renderKeyboard()

    act(() => press('ArrowRight'))
    act(() => press('Enter'))
    expect(callbacks.onOpen).toHaveBeenCalledWith(0)
    act(() => press(' '))
    expect(callbacks.onToggleSelection).toHaveBeenCalledWith(0)
  })

  it('extends selection from the previous focus with Shift+Arrow', () => {
    renderKeyboard()

    act(() => press('ArrowRight'))
    act(() => press('ArrowRight', { shiftKey: true }))
    expect(callbacks.onExtendSelection).toHaveBeenCalledWith(0, 1)
  })

  it('uses list left and right as back and open', () => {
    renderKeyboard({ listMode: true })

    act(() => press('ArrowDown'))
    act(() => press('ArrowLeft'))
    expect(callbacks.onBack).toHaveBeenCalledOnce()
    act(() => press('ArrowRight'))
    expect(callbacks.onOpen).toHaveBeenCalledWith(0)
  })

  it('dispatches management shortcuts', () => {
    renderKeyboard()

    act(() => press('a', { ctrlKey: true }))
    expect(callbacks.onSelectAll).toHaveBeenCalledOnce()
    act(() => press('/'))
    expect(callbacks.onFocusSearch).toHaveBeenCalledOnce()
    act(() => press('Backspace'))
    expect(callbacks.onBack).toHaveBeenCalledOnce()
    act(() => press('Delete'))
    expect(callbacks.onDelete).toHaveBeenCalledOnce()
    act(() => press('F2'))
    expect(callbacks.onEditMetadata).toHaveBeenCalledOnce()
    act(() => press('1', { altKey: true }))
    expect(callbacks.onTreeLayout).toHaveBeenCalledOnce()
    act(() => press('2', { altKey: true }))
    expect(callbacks.onColumnLayout).toHaveBeenCalledOnce()
    act(() => press('1', { ctrlKey: true }))
    expect(callbacks.onGridView).toHaveBeenCalledOnce()
    act(() => press('2', { ctrlKey: true }))
    expect(callbacks.onListView).toHaveBeenCalledOnce()
    act(() => press('Backspace', { metaKey: true }))
    expect(callbacks.onDelete).toHaveBeenCalledTimes(2)
    act(() => press('?'))
    expect(callbacks.onShowShortcuts).toHaveBeenCalledOnce()
    act(() => press('F6'))
    expect(callbacks.onCyclePane).toHaveBeenCalledOnce()
  })

  it('clears selection before clearing focus on Escape', () => {
    const { result } = renderKeyboard()
    act(() => press('ArrowRight'))
    callbacks.onClearSelection.mockReturnValueOnce(true)

    act(() => press('Escape'))
    expect(result.current.focusedIndex).toBe(0)
    act(() => press('Escape'))
    expect(result.current.focusedIndex).toBeNull()
  })

  it('does not intercept typing targets or dialogs', () => {
    renderKeyboard()
    const input = document.createElement('input')
    const dialog = document.createElement('div')
    const dialogButton = document.createElement('button')
    dialog.setAttribute('role', 'dialog')
    dialog.append(dialogButton)
    document.body.append(input, dialog)

    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, bubbles: true }))
    dialogButton.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }))

    expect(callbacks.onSelectAll).not.toHaveBeenCalled()
    expect(callbacks.onDelete).not.toHaveBeenCalled()
    input.remove()
    dialog.remove()
  })
})
