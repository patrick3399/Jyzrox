/**
 * Single-page mode keeps the previous and next page mounted as hidden slots, so
 * turning back to a page the reader already showed reuses its element instead
 * of asking the browser for the image again.
 *
 * Before this, one <img> had its `src` swapped on every page turn. Whether
 * 10 → 11 → 10 needed the network was left entirely to the browser HTTP cache,
 * which on a slow connection (and on iOS in particular) is not something the
 * reader can count on.
 */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, act } from '@testing-library/react'
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

// The prefetcher loads through `new Image()`, which jsdom never completes.
// This stand-in lets a test decide when a prefetch settles.
interface FakePrefetchImage {
  src: string
  onload: (() => void) | null
  onerror: (() => void) | null
}
let prefetchImages: FakePrefetchImage[] = []

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', AutoFireResizeObserver)
  // jsdom leaves media playback unimplemented; VideoPlayer chains on play().
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
  HTMLMediaElement.prototype.pause = vi.fn()
  vi.stubGlobal(
    'Image',
    class {
      src = ''
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor() {
        prefetchImages.push(this)
      }
    },
  )
})

beforeEach(() => {
  prefetchImages = []
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

function makeGalleryImages(
  count: number,
  overrides: Record<number, Partial<GalleryImage>> = {},
): GalleryImage[] {
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
    ...overrides[i + 1],
  }))
}

function renderLocalReader(images: GalleryImage[] = makeGalleryImages(20)) {
  return render(
    <Reader
      source="local"
      sourceId="1"
      downloadStatus="complete"
      images={images}
      totalPages={images.length}
    />,
  )
}

function turn(key: 'ArrowRight' | 'ArrowLeft') {
  fireEvent.keyDown(window, { key })
}

/** The main-view element for a page (thumbnails use a different alt text). */
function pageImg(page: number): HTMLImageElement | null {
  return document.querySelector<HTMLImageElement>(`img[alt="Page ${page}"]`)
}

function finishLoading(page: number) {
  const img = pageImg(page)
  if (!img) throw new Error(`Page ${page} is not mounted`)
  fireEvent.load(img)
}

/** Settle the prefetcher's in-flight request for a URL ending in `urlSuffix`. */
function settlePrefetch(urlSuffix: string) {
  const request = prefetchImages.find((img) => img.src.endsWith(urlSuffix))
  if (!request) throw new Error(`No prefetch in flight for ${urlSuffix}`)
  act(() => {
    request.onload?.()
  })
}

describe('Reader single-page neighbour retention', () => {
  it('keeps the page 1 element mounted but hidden after turning to page 2', () => {
    renderLocalReader()
    finishLoading(1)
    const page1 = pageImg(1)

    turn('ArrowRight')

    expect(pageImg(1)).toBe(page1)
    expect(pageImg(1)?.style.display).toBe('none')
    expect(pageImg(2)?.style.display).toBe('')
  })

  it('shows the very same page 1 element again when turning back from page 2', () => {
    renderLocalReader()
    finishLoading(1)
    const page1 = pageImg(1)
    turn('ArrowRight')
    finishLoading(2)

    turn('ArrowLeft')

    expect(pageImg(1)).toBe(page1)
    expect(pageImg(1)?.style.display).toBe('')
    expect(pageImg(2)?.style.display).toBe('none')
  })

  it('does not mount the next page while the prefetcher has not loaded it', () => {
    renderLocalReader()
    finishLoading(1)

    expect(pageImg(2)).toBeNull()
  })

  it('mounts the next page hidden once the prefetcher reports it loaded', () => {
    renderLocalReader()
    finishLoading(1)

    settlePrefetch('/media/test/2.jpg')

    expect(pageImg(2)).not.toBeNull()
    expect(pageImg(2)?.style.display).toBe('none')
  })

  it('drops a page once it is more than one page away', () => {
    renderLocalReader()
    finishLoading(1)
    turn('ArrowRight')
    finishLoading(2)

    turn('ArrowRight')

    expect(pageImg(1)).toBeNull()
    expect(pageImg(2)?.style.display).toBe('none')
  })

  it('never retains a video page as a hidden neighbour', () => {
    renderLocalReader(
      makeGalleryImages(20, { 2: { media_type: 'video', filename: '2.mp4', file_path: '/data/test/2.mp4' } }),
    )
    finishLoading(1)
    turn('ArrowRight')
    const video = document.querySelector('video')
    if (!video) throw new Error('Page 2 should render a <video>')
    fireEvent.loadedMetadata(video)

    turn('ArrowRight')

    expect(document.querySelector('video')).toBeNull()
  })

  it('does not show the spinner when turning onto a retained page that already loaded', () => {
    renderLocalReader()
    finishLoading(1)
    turn('ArrowRight')
    finishLoading(2)

    turn('ArrowLeft')
    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(document.querySelector('[data-testid="reader-page-loading"]')).toBeNull()
  })

  it('in proxy mode does not mount the next page from the prefetcher report', () => {
    const images = makeGalleryImages(20).map((img) => ({ ...img, file_path: null, thumb_path: null }))
    render(
      <Reader
        source="ehentai"
        sourceId="1"
        downloadStatus="proxy_only"
        images={images}
        totalPages={images.length}
      />,
    )
    finishLoading(1)

    settlePrefetch('/api/eh/image-proxy/1/2')

    expect(pageImg(2)).toBeNull()
  })

  it('in proxy mode still keeps the previous page mounted after turning forward', () => {
    const images = makeGalleryImages(20).map((img) => ({ ...img, file_path: null, thumb_path: null }))
    render(
      <Reader
        source="ehentai"
        sourceId="1"
        downloadStatus="proxy_only"
        images={images}
        totalPages={images.length}
      />,
    )
    finishLoading(1)
    const page1 = pageImg(1)

    turn('ArrowRight')

    expect(pageImg(1)).toBe(page1)
    expect(pageImg(1)?.style.display).toBe('none')
  })
})
