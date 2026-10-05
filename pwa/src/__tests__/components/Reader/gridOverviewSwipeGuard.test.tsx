/**
 * Regression: scrolling inside the grid overview (a finger swipe upward,
 * i.e. scrolling the content down) bubbled up to the Reader's own swipe-up
 * container gesture and was misread as "swipe up to exit", closing the whole
 * Reader instead of just scrolling the grid. useTouchGesture is attached to
 * the outer reader-container, and its isDisabled callback only checked zoom
 * state — not whether the grid overview was open.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import Reader from '@/components/Reader'
import type { GalleryImage } from '@/lib/types'

const back = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back, push: vi.fn(), replace: vi.fn() }),
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

// @tanstack/react-virtual needs a real-ish viewport in jsdom, same shim as
// ThumbnailGridOverlay.test.tsx.
class AutoFireResizeObserver {
  private callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }
  observe(target: Element) {
    const rect = { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON() {} }
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
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 600 })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 800 })
  HTMLElement.prototype.getBoundingClientRect = () =>
    ({ width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON() {} }) as DOMRect
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

function swipeUp(el: Element) {
  fireEvent.touchStart(el, { touches: [{ clientX: 100, clientY: 500 }] })
  fireEvent.touchEnd(el, { changedTouches: [{ clientX: 100, clientY: 300 }] })
}

describe('Reader grid overview vs swipe-up-to-exit gesture', () => {
  beforeEach(() => {
    back.mockClear()
  })

  it('does not exit the Reader on a swipe-up gesture while the grid overview is open', async () => {
    render(
      <Reader
        source="local"
        sourceId="1"
        downloadStatus="complete"
        images={makeGalleryImages(20)}
        totalPages={20}
      />,
    )

    fireEvent.click(screen.getByLabelText('reader.gridOverview'))
    await act(async () => {})

    const container = document.querySelector('.reader-container')
    expect(container).not.toBeNull()
    swipeUp(container as Element)

    expect(back).not.toHaveBeenCalled()
  })

  it('control: the same swipe-up gesture exits the Reader when the grid overview is closed', () => {
    render(
      <Reader
        source="local"
        sourceId="1"
        downloadStatus="complete"
        images={makeGalleryImages(20)}
        totalPages={20}
      />,
    )

    const container = document.querySelector('.reader-container')
    expect(container).not.toBeNull()
    swipeUp(container as Element)

    expect(back).toHaveBeenCalledTimes(1)
  })
})
