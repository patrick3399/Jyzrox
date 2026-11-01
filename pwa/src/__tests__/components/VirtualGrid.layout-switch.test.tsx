/**
 * VirtualGrid restore across a layout switch, driven by the real window virtualizer.
 *
 * A Library layout switch commits a restore request together with new `columns`
 * (density/list) or a new `gap`. The restore effect must wait until the grid
 * has actually settled on the new layout, and must re-target its row when the
 * column count changes under a pending request.
 */
import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VirtualGrid } from '@/components/VirtualGrid'

const ESTIMATE = 220
const GAP = 8
const MEASURED_ROW = 268
const LANDING_OFFSET = 51

type Item = { id: number }
const items: Item[] = Array.from({ length: 120 }, (_, id) => ({ id }))

type ObserverRecord = { callback: ResizeObserverCallback; targets: Set<Element> }
let observers: ObserverRecord[] = []
let frameQueue: FrameRequestCallback[] = []
let clock = 0
let scrollY = 0
let scrollWrites: number[] = []
let offsetHeightDescriptor: PropertyDescriptor | undefined

class RecordingResizeObserver {
  private record: ObserverRecord
  constructor(callback: ResizeObserverCallback) {
    this.record = { callback, targets: new Set() }
    observers.push(this.record)
  }
  observe(target: Element) {
    this.record.targets.add(target)
  }
  unobserve(target: Element) {
    this.record.targets.delete(target)
  }
  disconnect() {
    this.record.targets.clear()
  }
}

function resizeContainer(container: HTMLElement, width: number) {
  const record = observers.find((entry) => entry.targets.has(container))
  if (!record) throw new Error('VirtualGrid is not observing its container')
  act(() => {
    record.callback(
      [{ contentRect: { width } } as unknown as ResizeObserverEntry],
      {} as ResizeObserver,
    )
  })
}

/** One rendering frame: scroll events are dispatched before animation callbacks. */
function frame() {
  act(() => {
    clock += 16
    window.dispatchEvent(new Event('scroll'))
    const callbacks = frameQueue
    frameQueue = []
    for (const callback of callbacks) callback(clock)
  })
}

function frames(count: number) {
  for (let index = 0; index < count; index += 1) frame()
}

function setOffsetTop(element: HTMLElement, value: number) {
  Object.defineProperty(element, 'offsetTop', { value, configurable: true })
}

/** Document-space top of a rendered row, as the consumer would read it from layout. */
function rowTop(container: HTMLElement, index: number) {
  const row = container.querySelector<HTMLElement>(`[data-index="${index}"]`)
  const match = /translateY\((-?[\d.]+)px\)/.exec(row?.style.transform ?? '')
  if (!match) throw new Error(`row ${index} is not rendered`)
  return container.offsetTop + Number(match[1])
}

function grid(props: Partial<React.ComponentProps<typeof VirtualGrid<Item>>>) {
  return (
    <VirtualGrid
      items={items}
      columns={{ base: 1 }}
      getItemKey={(item) => item.id}
      gap={GAP}
      estimateHeight={ESTIMATE}
      renderItem={(item) => <span>{item.id}</span>}
      {...props}
    />
  )
}

beforeEach(() => {
  observers = []
  frameQueue = []
  clock = 0
  scrollY = 0
  scrollWrites = []
  vi.stubGlobal('ResizeObserver', RecordingResizeObserver)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frameQueue.push(callback)
    return frameQueue.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  vi.stubGlobal('scrollTo', (first?: number | ScrollToOptions, second?: number) => {
    const top = typeof first === 'object' ? first.top : second
    scrollY = Math.max(0, top ?? 0)
    scrollWrites.push(scrollY)
  })
  vi.spyOn(performance, 'now').mockImplementation(() => clock)
  Object.defineProperty(window, 'scrollY', { get: () => scrollY, configurable: true })
  Object.defineProperty(window, 'innerWidth', { value: 1920, configurable: true })
  Object.defineProperty(document.documentElement, 'scrollHeight', {
    get: () => 1_000_000,
    configurable: true,
  })
  offsetHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    get(this: HTMLElement) {
      return this.hasAttribute('data-index') ? MEASURED_ROW : 0
    },
    configurable: true,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document.documentElement, 'scrollHeight')
  if (offsetHeightDescriptor) {
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', offsetHeightDescriptor)
  }
})

function cellRow(container: HTMLElement, index: number): number | null {
  const cell = container.querySelector(`[data-grid-index="${index}"]`)
  const row = cell?.closest('[data-index]')
  return row ? Number(row.getAttribute('data-index')) : null
}

const ROW = ESTIMATE + GAP

describe('VirtualGrid restore across a layout switch', () => {
  it('test_request_committed_with_new_columns_is_not_applied_until_colcount_settles_then_lands', () => {
    const twoCols = { base: 2 }
    const fourCols = { base: 4 }
    const view = render(grid({ columns: twoCols, measureRows: false }))
    const container = view.container.firstElementChild as HTMLElement
    setOffsetTop(container, 100)
    resizeContainer(container, 1000)
    frames(2)
    // Index 5 is on screen in both layouts (row 2 with 2 columns, row 1 with 4).
    expect(cellRow(container, 5)).toBe(2)

    const appliedInRow: Array<number | null> = []
    const onRestoreApplied = vi.fn(() => {
      appliedInRow.push(cellRow(container, 5))
      window.scrollTo(0, rowTop(container, 1) + LANDING_OFFSET)
    })
    // The switch: new columns and the restore request arrive in one commit.
    view.rerender(
      grid({
        columns: fourCols,
        measureRows: false,
        restoreRequest: { key: 'layout-switch:1', index: 5 },
        onRestoreApplied,
      }),
    )

    // Still on the old colCount: nothing may be reported as applied.
    expect(onRestoreApplied).not.toHaveBeenCalled()

    resizeContainer(container, 1000)
    frames(8)

    expect(onRestoreApplied).toHaveBeenCalledTimes(1)
    // It was applied in the new layout (4 columns => index 5 sits in row 1).
    expect(appliedInRow).toEqual([1])
    expect(window.scrollY - rowTop(container, 1)).toBe(LANDING_OFFSET)
  })

  it('test_gap_only_change_lands_using_row_transforms_of_the_new_gap', () => {
    const NEW_GAP = 40
    const view = render(grid({ measureRows: false, gap: GAP }))
    const container = view.container.firstElementChild as HTMLElement
    setOffsetTop(container, 100)
    resizeContainer(container, 1000)
    frames(2)
    expect(rowTop(container, 5)).toBe(100 + 5 * ROW)

    const topsAtApply: number[] = []
    const onRestoreApplied = vi.fn(() => {
      // The consumer reads positions from what is rendered right now.
      const top = rowTop(container, 5)
      topsAtApply.push(top)
      window.scrollTo(0, top + LANDING_OFFSET)
    })
    view.rerender(
      grid({
        measureRows: false,
        gap: NEW_GAP,
        restoreRequest: { key: 'layout-switch:1', index: 5 },
        onRestoreApplied,
      }),
    )
    frames(8)

    expect(onRestoreApplied).toHaveBeenCalledTimes(1)
    // Stale transforms (old gap) would give 100 + 5 * ROW here.
    expect(topsAtApply).toEqual([100 + 5 * (ESTIMATE + NEW_GAP)])
    expect(window.scrollY).toBe(100 + 5 * (ESTIMATE + NEW_GAP) + LANDING_OFFSET)
    expect(window.scrollY - rowTop(container, 5)).toBe(LANDING_OFFSET)
  })

  it('test_pending_restore_reissues_its_row_when_the_column_count_changes', () => {
    const view = render(grid({ columns: { base: 2 }, measureRows: false }))
    const container = view.container.firstElementChild as HTMLElement
    setOffsetTop(container, 100)
    resizeContainer(container, 1000)
    frames(2)
    scrollWrites = []
    const onRestoreApplied = vi.fn()
    const restoreRequest = { key: 'search:restore:1', index: 40 }

    // Issued for 2 columns: item 40 is in row 20, far outside the rendered rows.
    view.rerender(
      grid({ columns: { base: 2 }, measureRows: false, restoreRequest, onRestoreApplied }),
    )
    expect(scrollWrites).toContain(100 + 20 * ROW)
    expect(onRestoreApplied).not.toHaveBeenCalled()

    // The layout changes to 4 columns before the anchor ever rendered.
    view.rerender(
      grid({ columns: { base: 4 }, measureRows: false, restoreRequest, onRestoreApplied }),
    )
    resizeContainer(container, 1000)
    frames(8)

    // Item 40 is in row 10 now; the request must have been re-issued for it.
    expect(scrollWrites).toContain(100 + 10 * ROW)
    expect(onRestoreApplied).toHaveBeenCalledTimes(1)
    expect(cellRow(container, 40)).toBe(10)
  })

  it('test_landed_restore_is_not_replayed_when_the_column_count_changes_afterwards', () => {
    const view = render(grid({ columns: { base: 2 }, measureRows: false }))
    const container = view.container.firstElementChild as HTMLElement
    setOffsetTop(container, 100)
    resizeContainer(container, 1000)
    frames(2)
    const onRestoreApplied = vi.fn()
    const restoreRequest = { key: 'search:restore:1', index: 5 }
    view.rerender(
      grid({ columns: { base: 2 }, measureRows: false, restoreRequest, onRestoreApplied }),
    )
    frames(4)
    expect(onRestoreApplied).toHaveBeenCalledTimes(1)

    view.rerender(
      grid({ columns: { base: 4 }, measureRows: false, restoreRequest, onRestoreApplied }),
    )
    resizeContainer(container, 1000)
    frames(8)

    // The applied token carries no colCount, so the same request never fires twice.
    expect(onRestoreApplied).toHaveBeenCalledTimes(1)
  })
})
