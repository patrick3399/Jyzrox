import { describe, expect, it, vi, beforeAll, afterEach } from 'vitest'
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

  describe('when neither measurement path ever reports a usable width', () => {
    // Belt-and-suspenders: even if window.innerWidth itself were 0 *and*
    // getBoundingClientRect/ResizeObserver never correct it, cellWidth must
    // never go negative and content must never render at a broken size —
    // the safe fallback is a loading state instead.
    let originalGetBoundingClientRect: typeof HTMLElement.prototype.getBoundingClientRect
    let originalInnerWidth: number

    beforeAll(() => {
      originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect
      originalInnerWidth = window.innerWidth
    })

    afterEach(() => {
      HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalInnerWidth })
      vi.unstubAllGlobals()
      vi.stubGlobal('ResizeObserver', AutoFireResizeObserver)
    })

    it('shows a loading state instead of a negative-height thumbnail grid', () => {
      class NeverFiresResizeObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
      }
      vi.stubGlobal('ResizeObserver', NeverFiresResizeObserver)
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: 0 })
      HTMLElement.prototype.getBoundingClientRect = () =>
        ({
          width: 0,
          height: 800,
          top: 0,
          left: 0,
          right: 0,
          bottom: 800,
          x: 0,
          y: 0,
          toJSON() {},
        }) as DOMRect

      render(
        <ThumbnailGridOverlay
          images={makeImages(20)}
          currentPage={1}
          onSelect={vi.fn()}
          onClose={vi.fn()}
        />,
      )

      expect(screen.queryByTitle('Page 1')).not.toBeInTheDocument()
      expect(screen.getByRole('status')).toBeInTheDocument()
    })
  })

  describe('before the precise DOM measurement resolves', () => {
    // Regression: @tanstack/react-virtual's own internal layout effect
    // measures and caches per-row positions on the *first* render, before
    // this component's own useLayoutEffect (which reads the real
    // scrollRef.getBoundingClientRect()) ever runs — and that cache does not
    // get recomputed later just because a subsequent render passes a
    // different `estimateSize`. Gating the container width's initial state on
    // `hasMeasured`/getBoundingClientRect (as a prior version of this
    // component did, starting from 0) fed the virtualizer a near-zero
    // estimate on that first pass, permanently caching several rows on top of
    // each other near the top of the scroll area — reproduced live as pages
    // 25/28/31/34 (three apart, i.e. one per column) all rendering in the same
    // spot. Seeding the initial state from window.innerWidth instead means
    // the very first render already uses a real width, so that first
    // internal measurement is correct from the start.
    let originalGetBoundingClientRect: typeof HTMLElement.prototype.getBoundingClientRect
    let originalInnerWidth: number

    beforeAll(() => {
      originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect
      originalInnerWidth = window.innerWidth
    })

    afterEach(() => {
      HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalInnerWidth })
      vi.unstubAllGlobals()
      vi.stubGlobal('ResizeObserver', AutoFireResizeObserver)
    })

    it('renders real thumbnails on first paint using the window.innerWidth estimate', () => {
      // getBoundingClientRect/ResizeObserver never resolve to anything useful
      // here (simulating imprecise/delayed DOM measurement) — only
      // window.innerWidth carries a real value, exactly like the very first
      // render in a real browser before any effect has run.
      class NeverFiresResizeObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
      }
      vi.stubGlobal('ResizeObserver', NeverFiresResizeObserver)
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
      HTMLElement.prototype.getBoundingClientRect = () =>
        ({
          width: 0,
          height: 0,
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          x: 0,
          y: 0,
          toJSON() {},
        }) as DOMRect

      render(
        <ThumbnailGridOverlay
          images={makeImages(20)}
          currentPage={1}
          onSelect={vi.fn()}
          onClose={vi.fn()}
        />,
      )

      // Real thumbnails render immediately — not stuck on the loading state —
      // because the initial estimate was never a broken width to begin with.
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
      expect(screen.getByTitle('Page 1')).toBeInTheDocument()
    })
  })
})
