/**
 * VirtualGrid restore hand-off, driven by the real window virtualizer.
 *
 * A restore is two scroll writes: the grid asks the virtualizer to bring the
 * anchor row to the top of the viewport, then the consumer lands on the exact
 * saved position, which sits some pixels away from that row start. The
 * virtualizer keeps reconciling towards its own target until it sees the
 * viewport there, so unless the grid retargets it at the consumer's landing it
 * either overrides the landing on the next frame or stays armed and pulls the
 * viewport back to the row start the next time that row's offset is recomputed.
 *
 * jsdom has no layout, so the harness supplies the pieces the virtualizer reads:
 * a scrollable document, frame-ordered scroll events, and row heights.
 */
import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VirtualGrid } from '@/components/VirtualGrid'

const ESTIMATE = 220
const GAP = 8
const MEASURED_ROW = 268
const LANDING_OFFSET = 51

type Item = { id: number }
const items: Item[] = Array.from({ length: 60 }, (_, id) => ({ id }))

type ObserverRecord = { callback: ResizeObserverCallback; targets: Set<Element> }
let observers: ObserverRecord[] = []
let frameQueue: FrameRequestCallback[] = []
let clock = 0
let scrollY = 0
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
  vi.stubGlobal('ResizeObserver', RecordingResizeObserver)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frameQueue.push(callback)
    return frameQueue.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  vi.stubGlobal('scrollTo', (first?: number | ScrollToOptions, second?: number) => {
    const top = typeof first === 'object' ? first.top : second
    scrollY = Math.max(0, top ?? 0)
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

describe('VirtualGrid restore hand-off', () => {
  it('keeps the consumer landing when rows above the anchor are first measured during the restore', () => {
    let container: HTMLElement | null = null
    const onRestoreApplied = vi.fn(() => {
      if (!container) return
      window.scrollTo(0, rowTop(container, 30) + LANDING_OFFSET)
    })
    const view = render(
      grid({ restoreRequest: { key: 'search:restore:1', index: 30 }, onRestoreApplied }),
    )
    container = view.container.firstElementChild as HTMLElement
    setOffsetTop(container, 247)
    resizeContainer(container, 1617)

    frames(8)

    expect(onRestoreApplied).toHaveBeenCalledTimes(1)
    expect(window.scrollY - rowTop(container, 30)).toBe(LANDING_OFFSET)
  })

  it('does not pull the viewport back to the anchor row when the grid offsetTop changes after restoring to an already rendered anchor', () => {
    // An in-page back navigation restores into a grid that is already showing
    // the anchor, so the landing follows the virtualizer's own write in the
    // same task instead of waiting for the anchor to materialize.
    const view = render(grid({ measureRows: false }))
    const container = view.container.firstElementChild as HTMLElement
    setOffsetTop(container, 247)
    resizeContainer(container, 1617)
    frames(2)
    const onRestoreApplied = vi.fn(() => {
      window.scrollTo(0, rowTop(container, 6) + LANDING_OFFSET)
    })

    view.rerender(
      grid({
        measureRows: false,
        restoreRequest: { key: 'search:restore:1', index: 6 },
        onRestoreApplied,
      }),
    )
    frames(8)
    const landing = window.scrollY
    expect(onRestoreApplied).toHaveBeenCalledTimes(1)
    expect(landing - rowTop(container, 6)).toBe(LANDING_OFFSET)

    // Content above the grid grows a second later (a results line, a banner):
    // the anchor row's offset is recomputed while the user is reading.
    frames(50)
    setOffsetTop(container, 283)
    resizeContainer(container, 1617)
    frames(8)

    expect(window.scrollY).toBe(landing)
  })

  it('repositions fixed-height rows when the row height changes without a column or margin change', () => {
    const view = render(
      grid({
        estimateHeight: ({ containerWidth }) => containerWidth / 10,
        measureRows: false,
      }),
    )
    const container = view.container.firstElementChild as HTMLElement
    resizeContainer(container, 1000)
    frames(2)

    resizeContainer(container, 2000)
    frames(2)

    const secondRow = container.querySelector<HTMLElement>('[data-index="1"]')
    expect(secondRow?.style.height).toBe('208px')
    expect(secondRow?.style.transform).toBe('translateY(208px)')
  })
})
