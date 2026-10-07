/**
 * Regression: the single-page loading spinner never appeared when the reader
 * returned to a page it had shown before, even though that page's image had to
 * load again.
 *
 * `handleImageLoaded` recorded every loaded page in `loadedPagesRef`, but the
 * page-change effect only consumes an entry when the load fired *before* the
 * effect ran. A page that loaded the normal way (effect first, load later)
 * left its entry behind for good, so the next visit took the "already loaded"
 * branch and skipped the spinner timer.
 */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import Reader from '@/components/Reader'
import type { GalleryImage } from '@/lib/types'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
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

function turn(key: 'ArrowRight' | 'ArrowLeft') {
  fireEvent.keyDown(window, { key })
}

function finishLoading(page: number) {
  fireEvent.load(screen.getByAltText(`Page ${page}`))
}

describe('Reader single-page loading spinner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the spinner when returning to a page whose image has to load again', () => {
    render(
      <Reader
        source="local"
        sourceId="1"
        downloadStatus="complete"
        images={makeGalleryImages(20)}
        totalPages={20}
      />,
    )

    finishLoading(1)
    turn('ArrowRight')
    finishLoading(2)
    turn('ArrowRight')
    finishLoading(3)
    turn('ArrowLeft')
    finishLoading(2)
    // Back on page 1, two pages away from where it was last shown: its image
    // is loading again and no load event has arrived yet.
    turn('ArrowLeft')

    act(() => {
      vi.advanceTimersByTime(200)
    })

    expect(screen.queryByTestId('reader-page-loading')).not.toBeNull()
  })

  it('control: shows the spinner on the first visit to a page that is still loading', () => {
    render(
      <Reader
        source="local"
        sourceId="1"
        downloadStatus="complete"
        images={makeGalleryImages(20)}
        totalPages={20}
      />,
    )

    finishLoading(1)
    turn('ArrowRight')

    act(() => {
      vi.advanceTimersByTime(200)
    })

    expect(screen.queryByTestId('reader-page-loading')).not.toBeNull()
  })
})
