/**
 * useExplorerSelection - Vitest test suite
 *
 * Covers Windows-Explorer selection semantics shared by gallery cards and image tiles:
 *   click / ctrl toggle / shift range / ctrl+shift additive range, selectAll / clear,
 *   and the drag marquee (threshold, rect intersection, additive, ignored targets).
 */
import { act, renderHook } from '@testing-library/react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MARQUEE_DRAG_THRESHOLD, useExplorerSelection } from '@/hooks/useExplorerSelection'

const KEYS = ['a', 'b', 'c', 'd', 'e']

type Rect = { left: number; top: number; right: number; bottom: number }

function withRect(element: HTMLElement, rect: Rect) {
  element.getBoundingClientRect = () =>
    ({ ...rect, x: rect.left, y: rect.top, width: rect.right - rect.left, height: rect.bottom - rect.top, toJSON: () => ({}) }) as DOMRect
}

/** A 500x500 scroll container at the viewport origin (jsdom reports 0 for layout metrics). */
function makeScroller(): HTMLDivElement {
  const scroller = document.createElement('div')
  document.body.appendChild(scroller)
  withRect(scroller, { left: 0, top: 0, right: 500, bottom: 500 })
  for (const [name, value] of Object.entries({ clientWidth: 500, clientHeight: 500, scrollWidth: 500, scrollHeight: 500 })) {
    Object.defineProperty(scroller, name, { configurable: true, value })
  }
  return scroller
}

/**
 * Item layout (client coordinates):
 *   a (60-110, 100-150)  b (120-170, 100-150)  c (180-230, 100-150)
 *   d (60-110, 200-250)  e (120-170, 200-250)
 */
const LAYOUT: Record<string, Rect> = {
  a: { left: 60, top: 100, right: 110, bottom: 150 },
  b: { left: 120, top: 100, right: 170, bottom: 150 },
  c: { left: 180, top: 100, right: 230, bottom: 150 },
  d: { left: 60, top: 200, right: 110, bottom: 250 },
  e: { left: 120, top: 200, right: 170, bottom: 250 },
}

interface PressOptions {
  target?: Element
  button?: number
  pointerType?: string
  ctrlKey?: boolean
  metaKey?: boolean
}

function setup(options: Partial<Parameters<typeof useExplorerSelection>[0]> = {}) {
  const scroller = makeScroller()
  const empty = document.createElement('div')
  scroller.appendChild(empty)
  const onMarqueeStart = vi.fn()
  const onBackgroundClick = vi.fn()
  const hook = renderHook(() =>
    useExplorerSelection({
      keys: KEYS,
      scrollRef: { current: scroller },
      onMarqueeStart,
      onBackgroundClick,
      ...options,
    }),
  )
  for (const key of KEYS) {
    const element = document.createElement('div')
    element.setAttribute('data-explorer-item', '')
    withRect(element, LAYOUT[key])
    scroller.appendChild(element)
    act(() => hook.result.current.registerItem(key, element))
  }

  const press = (x: number, y: number, opts: PressOptions = {}) =>
    act(() => {
      hook.result.current.onContainerPointerDown({
        button: opts.button ?? 0,
        pointerType: opts.pointerType ?? 'mouse',
        pointerId: 1,
        clientX: x,
        clientY: y,
        ctrlKey: opts.ctrlKey ?? false,
        metaKey: opts.metaKey ?? false,
        target: opts.target ?? empty,
      } as unknown as ReactPointerEvent<HTMLElement>)
    })
  const fire = (type: 'pointermove' | 'pointerup' | 'pointercancel', x: number, y: number) =>
    act(() => {
      scroller.dispatchEvent(Object.assign(new MouseEvent(type, { clientX: x, clientY: y }), { pointerId: 1 }))
    })
  const selected = () => [...hook.result.current.selectedKeys].sort()
  return { hook, scroller, empty, press, fire, selected, onMarqueeStart, onBackgroundClick }
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.style.userSelect = ''
})

describe('useExplorerSelection - click semantics', () => {
  it('plain click selects exactly one item and replaces the previous selection', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.onItemClick(1, {}))
    expect(selected()).toEqual(['b'])
    act(() => hook.result.current.onItemClick(3, {}))
    expect(selected()).toEqual(['d'])
  })

  it('ctrl (and meta) click toggles an item without touching the rest', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.onItemClick(0, {}))
    act(() => hook.result.current.onItemClick(2, { ctrlKey: true }))
    expect(selected()).toEqual(['a', 'c'])
    act(() => hook.result.current.onItemClick(0, { metaKey: true }))
    expect(selected()).toEqual(['c'])
  })

  it('shift click selects the range from the anchor and replaces other selections', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.onItemClick(0, {}))
    act(() => hook.result.current.onItemClick(3, {}))
    act(() => hook.result.current.onItemClick(1, { shiftKey: true }))
    // anchor is 3 (last plain click): range 1..3, 'a' dropped
    expect(selected()).toEqual(['b', 'c', 'd'])
  })

  it('shift click selects a backwards range from the anchor', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.onItemClick(3, {}))
    act(() => hook.result.current.onItemClick(1, { shiftKey: true }))
    expect(selected()).toEqual(['b', 'c', 'd'])
  })

  it('shift click without an anchor behaves like a plain click', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.onItemClick(2, { shiftKey: true }))
    expect(selected()).toEqual(['c'])
  })

  it('ctrl+shift click adds the range to the existing selection', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.onItemClick(0, {}))
    act(() => hook.result.current.onItemClick(2, { ctrlKey: true }))
    act(() => hook.result.current.onItemClick(4, { ctrlKey: true, shiftKey: true }))
    expect(selected()).toEqual(['a', 'c', 'd', 'e'])
  })

  it('coarse toggleOnClick makes a plain click toggle instead of replace', () => {
    const { hook, selected } = setup({ toggleOnClick: true })

    act(() => hook.result.current.onItemClick(0, {}))
    act(() => hook.result.current.onItemClick(1, {}))
    expect(selected()).toEqual(['a', 'b'])
    act(() => hook.result.current.onItemClick(0, {}))
    expect(selected()).toEqual(['b'])
  })

  it('selectAll selects every key and clear empties the selection and the anchor', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.selectAll())
    expect(selected()).toEqual(KEYS)
    act(() => hook.result.current.clear())
    expect(selected()).toEqual([])
    // anchor reset: a shift click now acts as a plain click
    act(() => hook.result.current.onItemClick(3, { shiftKey: true }))
    expect(selected()).toEqual(['d'])
  })

  it('extendTo selects the range between the anchor and the target index', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.selectOnly(1))
    act(() => hook.result.current.extendTo(1, 3))
    expect(selected()).toEqual(['b', 'c', 'd'])
    act(() => hook.result.current.extendTo(3, 0))
    expect(selected()).toEqual(['a', 'b'])
  })

  it('ignores out-of-range indexes', () => {
    const { hook, selected } = setup()

    act(() => hook.result.current.onItemClick(99, {}))
    act(() => hook.result.current.toggle(99))
    expect(selected()).toEqual([])
  })
})

describe('useExplorerSelection - marquee', () => {
  it('dragging beyond the threshold on empty space selects the items whose rect intersects', () => {
    const { hook, press, fire, selected, onMarqueeStart } = setup()

    press(50, 90)
    expect(selected()).toEqual([])
    fire('pointermove', 175, 160)

    expect(onMarqueeStart).toHaveBeenCalledTimes(1)
    expect(selected()).toEqual(['a', 'b'])
    expect(hook.result.current.marquee).toEqual({ left: 50, top: 90, width: 125, height: 70 })
  })

  it('growing the marquee adds items and shrinking it removes them again', () => {
    const { press, fire, selected } = setup()

    press(50, 90)
    fire('pointermove', 240, 260)
    expect(selected()).toEqual(['a', 'b', 'c', 'd', 'e'])
    fire('pointermove', 125, 160)
    expect(selected()).toEqual(['a', 'b'])
  })

  it('touching an item edge only is not an intersection', () => {
    const { press, fire, selected } = setup()

    press(10, 90)
    fire('pointermove', 60, 160)
    expect(selected()).toEqual([])
  })

  it('a non-additive marquee replaces the previous selection', () => {
    const { hook, press, fire, selected } = setup()
    act(() => hook.result.current.selectOnly(4))

    press(50, 90)
    fire('pointermove', 115, 160)

    expect(selected()).toEqual(['a'])
  })

  it('a ctrl-held marquee is additive and keeps the previous selection', () => {
    const { hook, press, fire, selected, onMarqueeStart } = setup()
    act(() => hook.result.current.selectOnly(4))

    press(50, 90, { ctrlKey: true })
    fire('pointermove', 115, 160)

    expect(selected()).toEqual(['a', 'e'])
    expect(onMarqueeStart).toHaveBeenCalledTimes(1)
    fire('pointerup', 115, 160)
    expect(selected()).toEqual(['a', 'e'])
  })

  it('releasing the pointer ends the marquee and keeps the selection', () => {
    const { hook, press, fire, selected, onBackgroundClick } = setup()

    press(50, 90)
    fire('pointermove', 175, 160)
    fire('pointerup', 175, 160)

    expect(hook.result.current.marquee).toBeNull()
    expect(selected()).toEqual(['a', 'b'])
    expect(onBackgroundClick).not.toHaveBeenCalled()
    expect(document.body.style.userSelect).toBe('')
  })

  it('a click below the drag threshold calls onBackgroundClick and clears instead of selecting', () => {
    const { hook, press, fire, selected, onBackgroundClick, onMarqueeStart } = setup()
    act(() => hook.result.current.selectOnly(0))

    press(65, 105)
    fire('pointermove', 65 + MARQUEE_DRAG_THRESHOLD - 2, 105)
    fire('pointerup', 65, 105)

    expect(onBackgroundClick).toHaveBeenCalledTimes(1)
    expect(onMarqueeStart).not.toHaveBeenCalled()
    expect(selected()).toEqual([])
    expect(hook.result.current.marquee).toBeNull()
  })

  it('a sub-threshold ctrl click leaves the selection alone and does not fire onBackgroundClick', () => {
    const { hook, press, fire, selected, onBackgroundClick } = setup()
    act(() => hook.result.current.selectOnly(0))

    press(300, 300, { ctrlKey: true })
    fire('pointerup', 300, 300)

    expect(onBackgroundClick).not.toHaveBeenCalled()
    expect(selected()).toEqual(['a'])
  })

  it('a cancelled pointer neither selects nor counts as a background click', () => {
    const { hook, press, fire, selected, onBackgroundClick } = setup()
    act(() => hook.result.current.selectOnly(0))

    press(300, 300)
    fire('pointercancel', 300, 300)

    expect(onBackgroundClick).not.toHaveBeenCalled()
    expect(selected()).toEqual(['a'])
    expect(hook.result.current.marquee).toBeNull()
  })

  it('a press on a [data-explorer-item] does not start a marquee', () => {
    const { scroller, press, fire, selected, onMarqueeStart, onBackgroundClick, hook } = setup()
    const item = scroller.querySelector('[data-explorer-item]')!

    press(70, 110, { target: item })
    fire('pointermove', 300, 300)
    fire('pointerup', 300, 300)

    expect(onMarqueeStart).not.toHaveBeenCalled()
    expect(onBackgroundClick).not.toHaveBeenCalled()
    expect(selected()).toEqual([])
    expect(hook.result.current.marquee).toBeNull()
  })

  it('a press on a button inside an item does not start a marquee', () => {
    const { scroller, press, fire, selected, onMarqueeStart } = setup()
    const button = document.createElement('button')
    scroller.querySelector('[data-explorer-item]')!.appendChild(button)

    press(70, 110, { target: button })
    fire('pointermove', 300, 300)

    expect(onMarqueeStart).not.toHaveBeenCalled()
    expect(selected()).toEqual([])
  })

  it.each([
    ['a right-button press', { button: 2 }],
    ['a touch pointer', { pointerType: 'touch' }],
  ])('%s does not start a marquee', (_label, opts) => {
    const { press, fire, selected, onMarqueeStart } = setup()

    press(50, 90, opts)
    fire('pointermove', 300, 300)

    expect(onMarqueeStart).not.toHaveBeenCalled()
    expect(selected()).toEqual([])
  })

  it('marqueeEnabled=false (coarse pointers) never starts a marquee', () => {
    const { press, fire, selected, onMarqueeStart } = setup({ marqueeEnabled: false })

    press(50, 90)
    fire('pointermove', 300, 300)

    expect(onMarqueeStart).not.toHaveBeenCalled()
    expect(selected()).toEqual([])
  })

  it('a press on the scrollbar gutter does not start a marquee', () => {
    const { press, fire, selected, onMarqueeStart } = setup()

    press(505, 90)
    fire('pointermove', 300, 300)

    expect(onMarqueeStart).not.toHaveBeenCalled()
    expect(selected()).toEqual([])
  })

  it('unregistering an item removes it from marquee hit testing', () => {
    const { hook, press, fire, selected } = setup()
    act(() => hook.result.current.registerItem('a', null))

    press(50, 90)
    fire('pointermove', 115, 160)

    expect(selected()).toEqual([])
  })
})
