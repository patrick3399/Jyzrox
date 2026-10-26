/**
 * Regression: the Retry button of a page that failed to load could not be
 * tapped in the paged views.
 *
 * The failed placeholder is rendered inside the page, which sits underneath
 * the tap zones and inherits `pointer-events: none` from the image scale
 * class. A tap on Retry reached a tap zone instead — the overlay toggled, or
 * the page turned, and the image stayed broken.
 *
 * jsdom does no hit testing, so these assert what decides it in a browser:
 * the button comes after the tap zones in the same stacking parent, and it is
 * not left with `pointer-events: none`.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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
    const rect = {
      width: 800,
      height: 600,
      top: 0,
      left: 0,
      right: 800,
      bottom: 600,
      x: 0,
      y: 0,
      toJSON() {},
    }
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

function renderReader() {
  return render(
    <Reader
      source="local"
      sourceId="1"
      backHref="/library"
      downloadStatus="complete"
      images={makeGalleryImages(4)}
      totalPages={4}
    />,
  )
}

/** True when a browser would let `button` take a tap that lands on it. */
function expectTappable(container: HTMLElement, button: HTMLElement) {
  const zones = Array.from(container.querySelectorAll<HTMLElement>('.reader-tap-zone'))
  expect(zones.length).toBeGreaterThan(0)
  for (const zone of zones) {
    expect(zone.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  }
  expect(button.className).toContain('pointer-events-auto')
}

describe('Reader failed page retry', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('puts Retry above the tap zones when a single-page image fails to load', () => {
    const { container } = renderReader()

    fireEvent.error(screen.getByAltText('Page 1'))

    expectTappable(container, screen.getByRole('button', { name: 'reader.retry' }))
  })

  it('puts Retry above the tap zones when a double-page image fails to load', () => {
    localStorage.setItem('reader_settings', JSON.stringify({ defaultViewMode: 'double' }))
    const { container } = renderReader()

    fireEvent.error(screen.getByAltText('Page 2'))

    expectTappable(container, screen.getByRole('button', { name: 'reader.retry' }))
  })

  it('requests the image again when Retry is tapped', () => {
    renderReader()
    fireEvent.error(screen.getByAltText('Page 1'))

    fireEvent.click(screen.getByRole('button', { name: 'reader.retry' }))

    expect(screen.getByAltText('Page 1').getAttribute('src')).toContain('_r=1')
    expect(screen.queryByRole('button', { name: 'reader.retry' })).toBeNull()
  })
})
