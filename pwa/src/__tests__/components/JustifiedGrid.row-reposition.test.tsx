/**
 * JustifiedGrid row positions, driven by the real window virtualizer.
 *
 * Justified rows have exact computed heights (`row.height + boxSpacing`). When
 * the container width changes the heights change while the row count can stay
 * the same. Measuring the rendered rows caches their sizes by row index, and the
 * cache does not follow the new heights, so the second row stays at the first
 * row's OLD height + spacing and overlaps or gaps against the first row.
 *
 * jsdom has no layout, so the harness supplies the pieces the virtualizer reads:
 * frame-ordered scroll events and a row `offsetHeight` taken from the row's own
 * inline height (which is what a browser would report for these rows).
 */
import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { JustifiedGrid } from '@/components/JustifiedGrid'

const SPACING = 4

type Item = { id: number }
const items: Item[] = Array.from({ length: 20 }, (_, id) => ({ id }))

type ObserverRecord = { callback: ResizeObserverCallback; targets: Set<Element> }
let observers: ObserverRecord[] = []
let frameQueue: FrameRequestCallback[] = []
let clock = 0
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

function grid(containerWidth: number) {
  return (
    <JustifiedGrid
      items={items}
      getAspectRatio={() => 1}
      containerWidth={containerWidth}
      boxSpacing={SPACING}
      renderItem={(item, { width, height }) => <span style={{ width, height }}>{item.id}</span>}
    />
  )
}

function row(container: HTMLElement, index: number): HTMLElement {
  const element = container.querySelector<HTMLElement>(`[data-index="${index}"]`)
  if (!element) throw new Error(`row ${index} is not rendered`)
  return element
}

function pixels(value: string): number {
  return Number.parseFloat(value)
}

function translateY(element: HTMLElement): number {
  const match = /translateY\((-?[\d.]+)px\)/.exec(element.style.transform)
  if (!match) throw new Error(`no translateY in ${element.style.transform}`)
  return Number(match[1])
}

beforeEach(() => {
  observers = []
  frameQueue = []
  clock = 0
  vi.stubGlobal('ResizeObserver', RecordingResizeObserver)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frameQueue.push(callback)
    return frameQueue.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  vi.stubGlobal('scrollTo', () => {})
  vi.spyOn(performance, 'now').mockImplementation(() => clock)
  offsetHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    get(this: HTMLElement) {
      return this.hasAttribute('data-index') ? pixels(this.style.height) : 0
    },
    configurable: true,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  if (offsetHeightDescriptor) {
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', offsetHeightDescriptor)
  }
})

describe('JustifiedGrid row positions', () => {
  it('repositions the second row at the first row new height when the container width changes but the row count stays', () => {
    const view = render(grid(1000))
    const container = view.container.firstElementChild as HTMLElement
    frames(3)
    const rowsBefore = container.querySelectorAll('[data-index]').length
    const firstHeightBefore = pixels(row(container, 0).style.height)
    expect(translateY(row(container, 1))).toBe(firstHeightBefore)

    view.rerender(grid(1040))
    frames(3)

    const first = row(container, 0)
    const firstHeightAfter = pixels(first.style.height)
    // Guard the scenario: the row heights really changed and no row appeared or vanished.
    expect(firstHeightAfter).not.toBe(firstHeightBefore)
    expect(container.querySelectorAll('[data-index]').length).toBe(rowsBefore)
    expect(translateY(row(container, 1))).toBe(translateY(first) + firstHeightAfter)
    expect(firstHeightAfter).toBeGreaterThan(SPACING)
  })
})
