/**
 * Regression: webtoon mode requested every original in the gallery at once.
 *
 * It mounted one eager `<img>` per page with no reserved height, so every page
 * sat inside the viewport as a 0px box and the browser fetched all of them —
 * 5,723 originals for one Instagram gallery. Each settled load also rebuilt a
 * Set of every loaded page and re-rendered the whole list.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

function makeGalleryImages(count: number, dims = true): GalleryImage[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    gallery_id: 1,
    page_num: i + 1,
    filename: `${i + 1}.jpg`,
    width: dims ? 800 : null,
    height: dims ? 1200 : null,
    file_path: `/data/test/${i + 1}.jpg`,
    thumb_path: null,
    file_size: 1000,
    file_hash: `hash${i + 1}`,
    media_type: 'image' as const,
    duration: null,
  }))
}

function renderWebtoon(images: GalleryImage[]) {
  return render(
    <Reader
      source="local"
      sourceId="1"
      backHref="/library"
      downloadStatus="complete"
      images={images}
      totalPages={images.length}
    />,
  )
}

function pageBox(container: HTMLElement, page: number): HTMLElement {
  const box = container.querySelector<HTMLElement>(`.reader-webtoon-scroll [data-page="${page}"]`)
  if (!box) throw new Error(`no webtoon box for page ${page}`)
  return box
}

describe('Reader webtoon pages', () => {
  beforeEach(() => {
    // jsdom has no layout, so it does not implement scrollIntoView.
    Element.prototype.scrollIntoView = vi.fn()
    // jsdom does not implement media playback.
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
    localStorage.clear()
    localStorage.setItem(
      'reader_settings',
      JSON.stringify({ defaultViewMode: 'webtoon', defaultScaleMode: 'fit-width' }),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('leaves every webtoon page image to the browser lazy loader', () => {
    renderWebtoon(makeGalleryImages(30))

    for (let page = 1; page <= 30; page++) {
      expect(screen.getByAltText(`Page ${page}`).getAttribute('loading')).toBe('lazy')
    }
  })

  it('reserves an unloaded webtoon page box from the image aspect ratio', () => {
    const { container } = renderWebtoon(makeGalleryImages(5))

    const box = pageBox(container, 3)
    expect(box.style.aspectRatio).toBe('800 / 1200')
    expect(box.style.width).toBe('100%')
  })

  it('reserves a full viewport for an unloaded webtoon page without dimensions', () => {
    const { container } = renderWebtoon(makeGalleryImages(5, false))

    expect(pageBox(container, 3).style.height).toBe('100vh')
  })

  it('reserves the box of an unloaded webtoon video page too', () => {
    const images = makeGalleryImages(5)
    images[2] = { ...images[2], file_path: '/data/test/3.mp4', media_type: 'video' }
    const { container } = renderWebtoon(images)

    expect(pageBox(container, 3).style.aspectRatio).toBe('800 / 1200')
  })

  // Regression: once loaded, a video page sized itself from the <video>. Away
  // from the screen the player drops its source and shrank to its poster (or
  // 300x150), and with no scroll anchoring in iOS Safari a fast scroll jumped.
  it('keeps the box of a webtoon video page reserved after its metadata loads', () => {
    const images = makeGalleryImages(5)
    images[2] = { ...images[2], file_path: '/data/test/3.mp4', media_type: 'video' }
    const { container } = renderWebtoon(images)

    fireEvent.loadedMetadata(pageBox(container, 3).querySelector('video') as HTMLVideoElement)

    expect(pageBox(container, 3).style.aspectRatio).toBe('800 / 1200')
  })

  it('releases the reserved box once that webtoon page has loaded or failed', () => {
    const { container } = renderWebtoon(makeGalleryImages(5))

    fireEvent.load(screen.getByAltText('Page 2'))
    fireEvent.error(screen.getByAltText('Page 4'))

    expect(pageBox(container, 2).style.cssText).toBe('')
    expect(pageBox(container, 4).style.cssText).toBe('')
    expect(pageBox(container, 3).style.aspectRatio).toBe('800 / 1200')
  })

  it('keeps the webtoon bottom spinner until the last page settles', () => {
    const { container } = renderWebtoon(makeGalleryImages(3))
    const spinner = () => container.querySelector('.reader-webtoon-scroll svg.animate-spin')

    fireEvent.load(screen.getByAltText('Page 1'))
    fireEvent.load(screen.getByAltText('Page 2'))
    expect(spinner()).not.toBeNull()

    fireEvent.load(screen.getByAltText('Page 3'))
    expect(spinner()).toBeNull()
  })
})
