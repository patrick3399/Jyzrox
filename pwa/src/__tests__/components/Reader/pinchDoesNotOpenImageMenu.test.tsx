/**
 * Regression: a two-finger pinch-zoom on a Reader page opened the image
 * long-press menu. The Reader's per-image long-press handlers started a fresh
 * 500 ms timer on every touchstart — including the second finger's — and
 * overwrote the ref holding the first one, so the first timer could no longer
 * be cancelled. Movement was only measured on touches[0], so a pinch that kept
 * the anchor finger still never cancelled the newer timer either. Any touch
 * that is not a single finger must cancel the pending long-press.
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
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
  // The help overlay would otherwise open on first mount.
  localStorage.setItem('reader_help_shown', '1')
})

beforeEach(() => {
  vi.useFakeTimers()
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

function renderReader() {
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
  const page = document.querySelector('.reader-container img')
  expect(page).not.toBeNull()
  return page as Element
}

const A = { identifier: 0, clientX: 150, clientY: 300 }
const B = { identifier: 1, clientX: 250, clientY: 400 }
const B_FAR = { identifier: 1, clientX: 330, clientY: 480 }

describe('Reader image long-press vs two-finger pinch', () => {
  it('does not open the image menu when a second finger lands and pinches with the first finger still', () => {
    const page = renderReader()

    fireEvent.touchStart(page, { touches: [A], changedTouches: [A] })
    act(() => {
      vi.advanceTimersByTime(100)
    })
    fireEvent.touchStart(page, { touches: [A, B], changedTouches: [B] })
    // Only the second finger moves: touches[0] (the anchor) stays put.
    fireEvent.touchMove(page, { touches: [A, B_FAR], changedTouches: [B_FAR] })
    act(() => {
      vi.advanceTimersByTime(1000)
    })

    expect(screen.queryByRole('menu')).toBeNull()

    fireEvent.touchEnd(page, { touches: [A], changedTouches: [B_FAR] })
    fireEvent.touchEnd(page, { touches: [], changedTouches: [A] })
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('does not open the image menu when both fingers land in the same touchstart', () => {
    const page = renderReader()

    fireEvent.touchStart(page, { touches: [A, B], changedTouches: [A, B] })
    act(() => {
      vi.advanceTimersByTime(1000)
    })

    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('does not reopen the image menu for the finger left on screen after a pinch', () => {
    const page = renderReader()

    fireEvent.touchStart(page, { touches: [A], changedTouches: [A] })
    fireEvent.touchStart(page, { touches: [A, B], changedTouches: [B] })
    fireEvent.touchMove(page, { touches: [A, B_FAR], changedTouches: [B_FAR] })
    // Lift one finger, keep the other resting on the page.
    fireEvent.touchEnd(page, { touches: [A], changedTouches: [B_FAR] })
    act(() => {
      vi.advanceTimersByTime(1000)
    })

    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('control: a single-finger hold still opens the image menu', () => {
    const page = renderReader()

    fireEvent.touchStart(page, { touches: [A], changedTouches: [A] })
    act(() => {
      vi.advanceTimersByTime(600)
    })

    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('does not turn the page when the finger slides away after the long-press menu opened', () => {
    localStorage.setItem('reader_settings', JSON.stringify({ statusBarShowClock: false }))
    const page = renderReader()
    const counter = () => document.querySelector('.reader-status-bar')?.textContent ?? ''
    expect(counter()).toContain('1 / 5')

    const start = { identifier: 0, clientX: 500, clientY: 300 }
    const slid = { identifier: 0, clientX: 150, clientY: 320 }
    fireEvent.touchStart(page, { touches: [start], changedTouches: [start] })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(screen.getByRole('menu')).toBeInTheDocument()
    // Slide towards a menu item and lift: a swipe left by the numbers.
    fireEvent.touchMove(page, { touches: [slid], changedTouches: [slid] })
    fireEvent.touchEnd(page, { touches: [], changedTouches: [slid] })

    expect(counter()).toContain('1 / 5')
    localStorage.removeItem('reader_settings')
  })
})
