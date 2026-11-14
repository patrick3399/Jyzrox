/**
 * Regression: double-tap to zoom swallowed the next real tap. usePinchZoom
 * calls preventDefault() on the second tap's touchend, so the browser never
 * dispatches that tap's click — but the tap zones only cleared their
 * "this was a double-tap" flag inside onClick. The flag stayed set and the
 * user's next tap (show controls, turn the page) was dropped.
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

beforeAll(() => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 800 })
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
  vi.useFakeTimers()
  localStorage.clear()
  localStorage.setItem('reader_help_shown', '1')
  localStorage.setItem('reader_settings', JSON.stringify({ statusBarShowClock: false }))
})

afterEach(() => {
  vi.useRealTimers()
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

function renderReader(viewMode: 'single' | 'double') {
  localStorage.setItem(
    'reader_settings',
    JSON.stringify({ statusBarShowClock: false, defaultViewMode: viewMode }),
  )
  render(
    <Reader
      source="local"
      sourceId="1"
      backHref="/library"
      downloadStatus="complete"
      images={makeGalleryImages(6)}
      totalPages={6}
    />,
  )
}

/** A tap whose click the browser delivers (nothing cancelled its touchend). */
function tap(el: Element, x: number, y: number) {
  const p = { identifier: 0, clientX: x, clientY: y }
  fireEvent.touchStart(el, { touches: [p], changedTouches: [p] })
  const notCancelled = fireEvent.touchEnd(el, { touches: [], changedTouches: [p] })
  if (notCancelled) fireEvent.click(el, { clientX: x, clientY: y })
}

function topBarShown() {
  const top = document.querySelector('.reader-overlay')
  return !(top?.className ?? '').includes('-translate-y-full')
}

describe.each(['single', 'double'] as const)(
  'Reader %s view: a tap after double-tap zoom is not swallowed',
  (viewMode) => {
    it('shows the controls on the first tap after a double-tap zoom', () => {
      renderReader(viewMode)
      const center = screen.getByLabelText('reader.toggleControls')

      // Double-tap to zoom in: the second touchend is cancelled, so no click.
      tap(center, 400, 300)
      act(() => {
        vi.advanceTimersByTime(100)
      })
      tap(center, 400, 300)
      act(() => {
        vi.advanceTimersByTime(1000)
      })
      expect(topBarShown()).toBe(false)

      // A later, separate tap must toggle the controls.
      tap(center, 400, 300)
      act(() => {
        vi.advanceTimersByTime(1000)
      })

      expect(topBarShown()).toBe(true)
    })
  },
)
