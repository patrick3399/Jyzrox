import { describe, expect, it, vi, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ThumbnailGridOverlay } from '@/components/Reader/ThumbnailGridOverlay'
import type { ReaderImage } from '@/components/Reader/types'

vi.mock('@/components/AppImage', () => ({
  AppImage: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

// @tanstack/react-virtual measures the scroll element's viewport size via
// ResizeObserver internally (no synchronous getBoundingClientRect fallback
// for that particular measurement), so a plain no-op stub leaves its visible
// range permanently empty in jsdom. Auto-firing the callback on observe()
// gives it (and this component's own ResizeObserver effect) a real size to
// work with — same fix shape as VirtualGrid.anchor.test.tsx's
// ControlledResizeObserver, just applied eagerly instead of on-demand.
class AutoFireResizeObserver {
  private callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }
  observe(target: Element) {
    const rect = { width: 1200, height: 800, top: 0, left: 0, right: 1200, bottom: 800, x: 0, y: 0, toJSON() {} }
    this.callback(
      [{ target, contentRect: rect } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    )
  }
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', AutoFireResizeObserver)
  // jsdom's default 0 makes the virtualizer compute an empty visible range —
  // give the scroll container a plausible viewport so at least the first
  // rows render for the click/interaction assertions below. Both the
  // component's own initial-width read (getBoundingClientRect) and
  // @tanstack/react-virtual's internal viewport measurement need this.
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    value: 800,
  })
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    value: 1200,
  })
  // @tanstack/virtual-core's own scroll-element measurement reads
  // offsetWidth/offsetHeight (not clientWidth/getBoundingClientRect) — jsdom
  // defaults both to 0, which is what actually kept getVirtualItems() empty.
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    value: 800,
  })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    value: 1200,
  })
  HTMLElement.prototype.getBoundingClientRect = () =>
    ({
      width: 1200,
      height: 800,
      top: 0,
      left: 0,
      right: 1200,
      bottom: 800,
      x: 0,
      y: 0,
      toJSON() {},
    }) as DOMRect
})

function makeImages(count: number): ReaderImage[] {
  return Array.from({ length: count }, (_, i) => ({
    pageNum: i + 1,
    url: `/media/cas/${i + 1}.jpg`,
    isLocal: true,
    mediaType: 'image' as const,
  }))
}

describe('ThumbnailGridOverlay', () => {
  it('renders a bounded window of cells, not every page, for a large gallery', () => {
    render(
      <ThumbnailGridOverlay
        images={makeImages(500)}
        currentPage={1}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    const buttons = screen.getAllByRole('button')
    // 500 pages must never all mount at once — the whole point of virtualizing.
    expect(buttons.length).toBeGreaterThan(0)
    expect(buttons.length).toBeLessThan(500)
  })

  it('highlights the current page', () => {
    render(
      <ThumbnailGridOverlay
        images={makeImages(20)}
        currentPage={3}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByTitle('Page 3').className).toContain('ring-2')
    expect(screen.getByTitle('Page 1').className).not.toContain('ring-2')
  })

  it('calls onSelect with the page number and onClose when a cell is clicked', () => {
    const onSelect = vi.fn()
    const onClose = vi.fn()
    render(
      <ThumbnailGridOverlay
        images={makeImages(20)}
        currentPage={1}
        onSelect={onSelect}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByTitle('Page 2'))
    expect(onSelect).toHaveBeenCalledWith(2)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on Escape', () => {
    const onClose = vi.fn()
    render(
      <ThumbnailGridOverlay
        images={makeImages(20)}
        currentPage={1}
        onSelect={vi.fn()}
        onClose={onClose}
      />,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on close-button click', () => {
    const onClose = vi.fn()
    render(
      <ThumbnailGridOverlay
        images={makeImages(20)}
        currentPage={1}
        onSelect={vi.fn()}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByLabelText('reader.closeGrid'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
