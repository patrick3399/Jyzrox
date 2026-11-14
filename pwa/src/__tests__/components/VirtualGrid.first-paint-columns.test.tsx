/**
 * The first grid a browser can paint must already use the container's column
 * count, not the `window.innerWidth` guess.
 *
 * Root cause: VirtualGrid seeded `colCount` from the window width (which
 * includes the desktop sidebar, one breakpoint too wide) and corrected it from
 * a passive effect. Passive effects run in a later task, after the browser has
 * painted the guessed layout, so every cell resized in place and pushed the
 * content below it down (Lighthouse CLS 0.14–0.25 on /library, /history,
 * /artists and gallery detail at 1350px).
 *
 * The test renders outside `act` so React schedules passive effects the way a
 * browser does, and samples the DOM from a MutationObserver: its microtask runs
 * at the end of the task that committed the grid, before the next paint.
 */
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { VirtualGrid } from '@/components/VirtualGrid'

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
    measure: () => {},
    scrollToIndex: () => {},
    scrollToOffset: () => {},
    options: { scrollMargin: options.scrollMargin },
    range: null,
  }),
}))

// Never fires: the correction must not depend on the observer's first callback.
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const columns = { base: 2, lg: 8, xl: 10 }
const items = Array.from({ length: 30 }, (_, i) => ({ id: String(i) }))

describe('VirtualGrid first paint', () => {
  let host: HTMLDivElement
  let root: Root
  let actEnv: unknown

  beforeEach(() => {
    actEnv = (globalThis as { IS_REACT_ACT_ENVIRONMENT?: unknown }).IS_REACT_ACT_ENVIRONMENT
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: unknown }).IS_REACT_ACT_ENVIRONMENT = false
    vi.stubGlobal('ResizeObserver', NoopResizeObserver)
    // Window is xl (10 columns); the container beside the sidebar is lg (8).
    Object.defineProperty(window, 'innerWidth', { value: 1350, configurable: true })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 1062,
      height: 0,
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 1062,
      bottom: 0,
      toJSON: () => ({}),
    } as DOMRect)
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
  })

  afterEach(() => {
    root.unmount()
    host.remove()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: unknown }).IS_REACT_ACT_ENVIRONMENT = actEnv
  })

  it('test_first_committed_grid_uses_container_columns_not_window_guess_when_sidebar_narrows_container', async () => {
    const painted: string[] = []
    const observer = new MutationObserver(() => {
      const grid = host.querySelector<HTMLElement>('[style*="grid-template-columns"]')
      if (grid) painted.push(grid.style.gridTemplateColumns)
    })
    observer.observe(host, { subtree: true, childList: true, attributes: true })
    const onColCountChange = vi.fn()

    root.render(
      <VirtualGrid
        items={items}
        columns={columns}
        getItemKey={(item) => item.id}
        onColCountChange={onColCountChange}
        renderItem={(item) => <span>{item.id}</span>}
      />,
    )

    await waitFor(() => expect(painted.length).toBeGreaterThan(0))
    // Let any later passive-effect correction land before asserting.
    await new Promise((resolve) => setTimeout(resolve, 20))
    observer.disconnect()

    expect(painted[0]).toBe('repeat(8, minmax(0, 1fr))')
    expect(painted).not.toContain('repeat(10, minmax(0, 1fr))')
    // The parent must end up with the measured count, not the guess.
    expect(onColCountChange).toHaveBeenLastCalledWith(8)
  })

  it('test_zero_width_container_keeps_window_guess_when_not_laid_out', async () => {
    vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockReturnValue({
      width: 0,
    } as DOMRect)
    const onColCountChange = vi.fn()

    root.render(
      <VirtualGrid
        items={items}
        columns={columns}
        getItemKey={(item) => item.id}
        onColCountChange={onColCountChange}
        renderItem={(item) => <span>{item.id}</span>}
      />,
    )

    await waitFor(() => expect(onColCountChange).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 20))
    const grid = host.querySelector<HTMLElement>('[style*="grid-template-columns"]')
    expect(grid?.style.gridTemplateColumns).toBe('repeat(10, minmax(0, 1fr))')
    expect(onColCountChange).toHaveBeenLastCalledWith(10)
  })
})
