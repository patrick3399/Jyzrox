/**
 * Regression: the Reader's container-level swipe detector (useTouchGesture)
 * read every touchend that reached it as a swipe:
 *
 * - It is a native listener on .reader-container, so it runs before React's
 *   root listener and the React stopPropagation() in the seek bar never hid
 *   the seek bar's drag from it. Horizontal drags on the seek bar and scrolls
 *   of the thumbnail strip were taken as page turns — and in webtoon mode a
 *   rightward one exits the Reader.
 * - The wheel handler skipped targets inside `.reader-overlay`, a class no
 *   element carried, so wheeling over the top bar or status bar flipped pages.
 * - It ignored a two-finger touchstart but still evaluated the touchend, using
 *   the lifted finger against the first finger's start. A pinch at 1x (the
 *   pinch hook clamps at 1, so nothing is zoomed and the guard stays open)
 *   turned the page or exited the Reader.
 */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Reader from '@/components/Reader'
import type { GalleryImage } from '@/lib/types'

const back = vi.fn()
const push = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back, push, replace: vi.fn() }),
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => '/reader/local/1',
}))

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      saveProgress: vi.fn().mockResolvedValue(undefined),
      deleteImage: vi.fn().mockResolvedValue(undefined),
      favoriteImage: vi.fn().mockResolvedValue(undefined),
      unfavoriteImage: vi.fn().mockResolvedValue(undefined),
      getProgress: vi.fn().mockResolvedValue(null),
    },
  },
}))

vi.mock('@/components/AppImage', () => ({
  AppImage: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', NoopResizeObserver)
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return []
      }
    },
  )
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 800 })
  Element.prototype.scrollIntoView = () => {}
  HTMLElement.prototype.scrollTo = () => {}
  HTMLElement.prototype.getBoundingClientRect = () =>
    ({
      width: 800,
      height: 600,
      top: 0,
      left: 0,
      right: 800,
      bottom: 600,
      x: 0,
      y: 0,
      toJSON() {},
    }) as DOMRect
})

beforeEach(() => {
  back.mockClear()
  push.mockClear()
  localStorage.clear()
  localStorage.setItem('reader_help_shown', '1')
  Object.defineProperty(window.history, 'length', { configurable: true, get: () => 3 })
})

afterEach(() => {
  delete (window.history as unknown as { length?: number }).length
})

function makeGalleryImages(count: number): GalleryImage[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    gallery_id: 1,
    page_num: i + 1,
    filename: `${i + 1}.jpg`,
    width: 800,
    height: 1200,
    file_path: `/data/test/${i + 1}.jpg`,
    thumb_path: `/data/test/thumbs/${i + 1}.jpg`,
    file_size: 1000,
    file_hash: `hash${i + 1}`,
    media_type: 'image' as const,
    duration: null,
  }))
}

function renderReader(viewMode: 'single' | 'webtoon' = 'single') {
  localStorage.setItem(
    'reader_settings',
    JSON.stringify({ defaultViewMode: viewMode, statusBarShowClock: false }),
  )
  render(
    <Reader
      source="local"
      sourceId="1"
      backHref="/library"
      downloadStatus="complete"
      images={makeGalleryImages(5)}
      totalPages={5}
    />,
  )
}

function exited() {
  return back.mock.calls.length + push.mock.calls.length > 0
}

/** The status bar's "current / total" counter. */
function shownPageCounter() {
  const bar = document.querySelector('.reader-status-bar')
  expect(bar).not.toBeNull()
  return bar?.textContent ?? ''
}

function drag(el: Element, fromX: number, toX: number, y = 590) {
  const start = { identifier: 0, clientX: fromX, clientY: y }
  const end = { identifier: 0, clientX: toX, clientY: y }
  fireEvent.touchStart(el, { touches: [start], changedTouches: [start] })
  fireEvent.touchMove(el, { touches: [end], changedTouches: [end] })
  fireEvent.touchEnd(el, { touches: [], changedTouches: [end] })
}

describe('Reader swipe detector only reads single-finger swipes on the page', () => {
  it('does not exit webtoon mode when the thumbnail strip is scrolled with a rightward drag', () => {
    renderReader('webtoon')
    const strip = document.querySelector('.reader-thumb-strip')
    expect(strip).not.toBeNull()

    drag(strip as Element, 100, 500)

    expect(exited()).toBe(false)
  })

  it('does not turn the page when the thumbnail strip is scrolled in single-page mode', () => {
    renderReader('single')
    expect(shownPageCounter()).toContain('1 / 5')
    const strip = document.querySelector('.reader-thumb-strip')

    drag(strip as Element, 500, 100)

    expect(shownPageCounter()).toContain('1 / 5')
  })

  it('does not exit webtoon mode when the status-bar seek bar is dragged rightward', () => {
    renderReader('webtoon')
    const seek = document.querySelector('.reader-status-bar .cursor-pointer')
    expect(seek).not.toBeNull()

    drag(seek as Element, 100, 700)

    expect(exited()).toBe(false)
  })

  it('does not turn the page when a pinch at 1x ends with the fingers far from the first start', () => {
    renderReader('single')
    const page = document.querySelector('.reader-container img')
    expect(page).not.toBeNull()
    const A = { identifier: 0, clientX: 400, clientY: 300 }
    const B = { identifier: 1, clientX: 100, clientY: 300 }
    // Pinching in: B moves towards A. The scale is clamped at 1.
    const B_IN = { identifier: 1, clientX: 250, clientY: 300 }

    fireEvent.touchStart(page as Element, { touches: [A], changedTouches: [A] })
    fireEvent.touchStart(page as Element, { touches: [A, B], changedTouches: [B] })
    fireEvent.touchMove(page as Element, { touches: [A, B_IN], changedTouches: [B_IN] })
    fireEvent.touchEnd(page as Element, { touches: [A], changedTouches: [B_IN] })
    fireEvent.touchEnd(page as Element, { touches: [], changedTouches: [A] })

    expect(shownPageCounter()).toContain('1 / 5')
    expect(exited()).toBe(false)
  })

  it('control: a one-finger swipe left on the page still turns to the next page', () => {
    renderReader('single')
    const page = document.querySelector('.reader-container img')

    drag(page as Element, 500, 200, 300)

    expect(shownPageCounter()).toContain('2 / 5')
  })

  it('control: a one-finger swipe right on a webtoon page still exits', () => {
    renderReader('webtoon')
    const page = document.querySelector('.reader-webtoon-scroll img')
    expect(page).not.toBeNull()

    drag(page as Element, 100, 500, 300)

    expect(exited()).toBe(true)
  })

  it('does not turn the page when the mouse wheel scrolls over the top control bar', () => {
    renderReader('single')
    const topBarButton = screen.getByLabelText('reader.gridOverview')

    fireEvent.wheel(topBarButton, { deltaY: 120 })

    expect(shownPageCounter()).toContain('1 / 5')
  })

  it('control: the mouse wheel over the page still turns to the next page', () => {
    renderReader('single')
    const page = document.querySelector('.reader-container img')

    fireEvent.wheel(page as Element, { deltaY: 120 })

    expect(shownPageCounter()).toContain('2 / 5')
  })
})
