import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VirtualGrid } from '@/components/VirtualGrid'

const { scrollToIndex } = vi.hoisted(() => ({ scrollToIndex: vi.fn() }))

vi.mock('@tanstack/react-virtual', () => ({
  useWindowVirtualizer: (options: { count: number; scrollMargin: number }) => ({
    getVirtualItems: () =>
      Array.from({ length: options.count }, (_, index) => ({
        index,
        key: index,
        start: index * 100,
        size: 100,
      })),
    getTotalSize: () => options.count * 100,
    measureElement: () => {},
    scrollToIndex,
    options: { scrollMargin: options.scrollMargin },
  }),
}))

let resizeCallback: ResizeObserverCallback | null = null

class ControlledResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback
  }
  observe() {}
  unobserve() {}
  disconnect() {}
}

type Item = { id: string; label: string }
const columns = { base: 2, md: 3 }

function grid(
  items: Item[],
  callbacks: {
    onVisibleRangeChange?: (range: { startIndex: number; endIndex: number }) => void
    onLayoutChange?: (layout: {
      colCount: number
      containerWidth: number
      scrollMargin: number
    }) => void
    restoreRequest?: { key: string; index: number }
    onRestoreApplied?: (request: { key: string; index: number }) => void
  } = {},
) {
  return (
    <VirtualGrid
      items={items}
      columns={columns}
      getItemKey={(item) => item.id}
      onVisibleRangeChange={callbacks.onVisibleRangeChange}
      onLayoutChange={callbacks.onLayoutChange}
      restoreRequest={callbacks.restoreRequest}
      onRestoreApplied={callbacks.onRestoreApplied}
      renderItem={(item) => <span data-testid={`item-${item.id}`}>{item.label}</span>}
    />
  )
}

describe('VirtualGrid browse-anchor contracts', () => {
  beforeEach(() => {
    resizeCallback = null
    scrollToIndex.mockReset()
    vi.stubGlobal('ResizeObserver', ControlledResizeObserver)
    Object.defineProperty(window, 'innerWidth', { value: 500, configurable: true })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('uses stable item keys so a reordered item retains its DOM identity', () => {
    const a = { id: 'a', label: 'A' }
    const b = { id: 'b', label: 'B' }
    const view = render(grid([a, b]))
    const originalA = screen.getByTestId('item-a')

    view.rerender(grid([b, a]))

    expect(screen.getByTestId('item-a')).toBe(originalA)
  })

  it('reports the visible item range needed to capture an anchor', () => {
    const onVisibleRangeChange = vi.fn()
    render(
      grid(
        [
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B' },
          { id: 'c', label: 'C' },
          { id: 'd', label: 'D' },
        ],
        { onVisibleRangeChange },
      ),
    )

    expect(onVisibleRangeChange).toHaveBeenLastCalledWith({ startIndex: 0, endIndex: 3 })
  })

  it('reports measured container layout after ResizeObserver corrects initial columns', () => {
    const onLayoutChange = vi.fn()
    const view = render(grid([{ id: 'a', label: 'A' }], { onLayoutChange }))
    const container = view.container.firstElementChild as HTMLElement
    Object.defineProperty(container, 'offsetTop', { value: 24, configurable: true })

    resizeCallback?.(
      [{ contentRect: { width: 800 } } as unknown as ResizeObserverEntry],
      {} as ResizeObserver,
    )

    expect(onLayoutChange).toHaveBeenLastCalledWith({
      colCount: 3,
      containerWidth: 800,
      scrollMargin: 24,
    })
  })

  it('applies an explicit restore only after ResizeObserver provides measured layout', () => {
    const onRestoreApplied = vi.fn()
    render(
      grid(
        [
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B' },
          { id: 'c', label: 'C' },
        ],
        { restoreRequest: { key: 'search:A', index: 2 }, onRestoreApplied },
      ),
    )

    expect(scrollToIndex).not.toHaveBeenCalled()
    expect(onRestoreApplied).not.toHaveBeenCalled()

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 800 } } as unknown as ResizeObserverEntry],
        {} as ResizeObserver,
      )
    })

    expect(scrollToIndex).toHaveBeenCalledWith(0, { align: 'start' })
    expect(onRestoreApplied).toHaveBeenCalledWith({ key: 'search:A', index: 2 })
  })

  it('waits for the requested item to materialize and register before acknowledging restore', () => {
    const onRestoreApplied = vi.fn()
    const callbacks = {
      restoreRequest: { key: 'search:A', index: 2 },
      onRestoreApplied,
    }
    const view = render(
      grid(
        [
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B' },
        ],
        callbacks,
      ),
    )
    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 800 } } as unknown as ResizeObserverEntry],
        {} as ResizeObserver,
      )
    })
    expect(scrollToIndex).not.toHaveBeenCalled()
    expect(onRestoreApplied).not.toHaveBeenCalled()

    view.rerender(
      grid(
        [
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B' },
          { id: 'c', label: 'C' },
        ],
        callbacks,
      ),
    )

    expect(scrollToIndex).toHaveBeenCalledWith(0, { align: 'start' })
    expect(onRestoreApplied).toHaveBeenCalledWith({ key: 'search:A', index: 2 })
  })

  it('re-applies the same key and index after the restore request is cleared', () => {
    const onRestoreApplied = vi.fn()
    const items = [
      { id: 'a', label: 'A' },
      { id: 'b', label: 'B' },
      { id: 'c', label: 'C' },
    ]
    const request = { key: 'search:A', index: 2 }
    const view = render(grid(items, { restoreRequest: request, onRestoreApplied }))

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 800 } } as unknown as ResizeObserverEntry],
        {} as ResizeObserver,
      )
    })
    expect(onRestoreApplied).toHaveBeenCalledTimes(1)

    view.rerender(grid(items, { onRestoreApplied }))
    view.rerender(grid(items, { restoreRequest: request, onRestoreApplied }))

    expect(onRestoreApplied).toHaveBeenCalledTimes(2)
    expect(scrollToIndex).toHaveBeenCalledTimes(2)
  })
})
