/**
 * Regression: tapping the screen edge did not turn the page on a video page.
 *
 * The edge tap zones used to cover the video controls, so they were removed
 * for every video page — which also removed the only one-handed way to move
 * on. A video page whose file had not arrived yet was worse: it mounts no
 * player either, so nothing on the page reacted to a tap at all.
 *
 * The zones only have to stay out of the way while the controls are showing.
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
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
  // jsdom implements neither; the player calls both as its visibility changes.
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})

function page(pageNum: number, over: Partial<GalleryImage> = {}): GalleryImage {
  return {
    id: pageNum,
    gallery_id: 1,
    page_num: pageNum,
    filename: `${pageNum}.jpg`,
    width: 800,
    height: 1200,
    file_path: `/data/test/${pageNum}.jpg`,
    thumb_path: `/data/test/thumbs/${pageNum}.jpg`,
    file_size: 1000,
    file_hash: `hash${pageNum}`,
    media_type: 'image' as const,
    duration: null,
    ...over,
  }
}

const video = (pageNum: number, over: Partial<GalleryImage> = {}) =>
  page(pageNum, {
    filename: `${pageNum}.mp4`,
    file_path: `/data/test/${pageNum}.mp4`,
    media_type: 'video',
    duration: 12,
    ...over,
  })

function renderOnMiddlePage(middle: GalleryImage) {
  return render(
    <Reader
      source="local"
      sourceId="1"
      downloadStatus="complete"
      images={[page(1), middle, page(3)]}
      totalPages={3}
      initialPage={2}
    />,
  )
}

const edgeZone = (container: HTMLElement, label: 'common.nextPage' | 'common.previousPage') =>
  container.querySelector<HTMLElement>(`.reader-tap-zone[aria-label="${label}"]`)

describe('Reader edge tap on non-image pages', () => {
  it('turns to the next page when the next edge is tapped on a video page', () => {
    const { container } = renderOnMiddlePage(video(2))
    expect(screen.queryByAltText('Page 3')).toBeNull()

    const next = edgeZone(container, 'common.nextPage')
    expect(next).not.toBeNull()
    fireEvent.click(next as HTMLElement)

    expect(screen.getByAltText('Page 3')).toBeInTheDocument()
  })

  it('turns to the previous page when the previous edge is tapped on a video page', () => {
    const { container } = renderOnMiddlePage(video(2))
    expect(screen.queryByAltText('Page 1')).toBeNull()

    const prev = edgeZone(container, 'common.previousPage')
    expect(prev).not.toBeNull()
    fireEvent.click(prev as HTMLElement)

    expect(screen.getByAltText('Page 1')).toBeInTheDocument()
  })

  it('removes the edge zones from a video page while its controls are showing', () => {
    const { container } = renderOnMiddlePage(video(2))

    // The player's own tap layer sits right after the <video> and toggles the overlay.
    const tapLayer = container.querySelector('video')?.nextElementSibling
    expect(tapLayer).not.toBeNull()
    fireEvent.click(tapLayer as Element)

    expect(edgeZone(container, 'common.nextPage')).toBeNull()
    expect(edgeZone(container, 'common.previousPage')).toBeNull()
  })

  it('keeps every tap zone on a video page whose file has not arrived yet', () => {
    const { container } = renderOnMiddlePage(video(2, { file_path: null }))
    expect(container.querySelector('video')).toBeNull()

    expect(edgeZone(container, 'common.nextPage')).not.toBeNull()
    expect(edgeZone(container, 'common.previousPage')).not.toBeNull()
    expect(
      container.querySelector('.reader-tap-zone[aria-label="reader.toggleControls"]'),
    ).not.toBeNull()
  })
})
