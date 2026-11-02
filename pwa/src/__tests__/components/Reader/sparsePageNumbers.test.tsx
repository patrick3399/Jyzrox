/**
 * page_num can have holes once a gallery is settled: a link gallery keeps the
 * numbers of the surviving pages when files are deleted from its folder, and a
 * download keeps source numbering around pages that failed. The API returns the
 * surviving pages only, so the Reader has to walk that list.
 *
 * Doing arithmetic on page_num instead showed an empty screen for every hole,
 * and capping it at `gallery.pages` (the number of surviving pages) made the
 * pages numbered above that cap unreachable.
 */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, screen } from '@testing-library/react'
import Reader from '@/components/Reader'
import type { Gallery, GalleryImage } from '@/lib/types'

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
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  vi.stubGlobal(
    'Image',
    class {
      src = ''
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
    },
  )
})

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('reader_help_shown', '1')
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

// Holes at 2 and 5-11; six surviving pages, the last numbered 14.
const SPARSE_PAGES = [1, 3, 4, 12, 13, 14]

function makeImages(pageNums: number[]): GalleryImage[] {
  return pageNums.map((page) => ({
    id: page,
    gallery_id: 1,
    page_num: page,
    filename: `${page}.png`,
    width: 800,
    height: 1200,
    file_path: `/data/test/${page}.png`,
    thumb_path: `/data/test/thumbs/${page}.png`,
    file_size: 1000,
    file_hash: `hash${page}`,
    media_type: 'image' as const,
    duration: null,
  }))
}

function renderReader({
  pages = SPARSE_PAGES,
  initialPage = 1,
  downloadStatus = 'complete',
}: {
  pages?: number[]
  initialPage?: number
  downloadStatus?: Gallery['download_status']
} = {}) {
  return render(
    <Reader
      source="local"
      sourceId="1"
      backHref="/library"
      downloadStatus={downloadStatus}
      images={makeImages(pages)}
      totalPages={pages.length}
      initialPage={initialPage}
    />,
  )
}

function turn(key: 'ArrowRight' | 'ArrowLeft') {
  fireEvent.keyDown(window, { key })
}

function counter(): string {
  return screen.getByTitle('reader.jumpToPage').textContent ?? ''
}

/** The page the main view is showing, ignoring neighbours kept mounted but hidden. */
function shownPage(): number | null {
  const shown = [...document.querySelectorAll<HTMLImageElement>('img[alt^="Page "]')].find(
    (img) => img.style.display !== 'none',
  )
  return shown ? Number(shown.alt.replace('Page ', '')) : null
}

function thumbnail(page: number): HTMLElement {
  const thumb = document.querySelector(`img[alt="Thumb ${page}"]`)?.closest('button')
  if (!thumb) throw new Error(`No thumbnail for page ${page}`)
  return thumb
}

describe('Reader with holes in page_num', () => {
  it('turns from page 1 to page 3 when page 2 was deleted', () => {
    renderReader()

    turn('ArrowRight')

    expect(shownPage()).toBe(3)
  })

  it('turns across a run of deleted pages instead of showing an empty screen', () => {
    renderReader({ initialPage: 4 })

    turn('ArrowRight')

    expect(shownPage()).toBe(12)
  })

  it('turns back across a hole', () => {
    renderReader({ initialPage: 12 })

    turn('ArrowLeft')

    expect(shownPage()).toBe(4)
  })

  it('reaches pages numbered above the surviving page count', () => {
    renderReader({ initialPage: 12 })

    turn('ArrowRight')
    turn('ArrowRight')

    expect(shownPage()).toBe(14)
  })

  it('stays on the last page when turning past it', () => {
    renderReader({ initialPage: 14 })

    turn('ArrowRight')

    expect(shownPage()).toBe(14)
  })

  it('opens a thumbnail numbered above the surviving page count', () => {
    renderReader()

    fireEvent.click(thumbnail(14))

    expect(shownPage()).toBe(14)
  })

  it('opens on the next surviving page when saved progress points at a hole', () => {
    renderReader({ initialPage: 5 })

    expect(shownPage()).toBe(12)
  })

  it('moves off the current page when a refresh removes it', () => {
    const { rerender } = renderReader({ initialPage: 3 })

    rerender(
      <Reader
        source="local"
        sourceId="1"
        backHref="/library"
        downloadStatus="complete"
        images={makeImages([1, 4, 12, 13, 14])}
        totalPages={5}
        initialPage={3}
      />,
    )

    expect(shownPage()).toBe(4)
  })

  it('counts surviving pages rather than showing the raw page number', () => {
    renderReader({ initialPage: 12 })

    expect(counter()).toBe('4 / 6')
  })

  it('jumps to the Nth surviving page from the page indicator', () => {
    renderReader()

    fireEvent.click(screen.getByTitle('reader.jumpToPage'))
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '4' } })
    fireEvent.click(screen.getByText('reader.go'))

    expect(shownPage()).toBe(12)
  })

  it('labels thumbnails with the same position the counter shows', () => {
    renderReader({ initialPage: 12 })

    expect(thumbnail(12).textContent).toBe('4')
  })

  it('still counts a page number that is not in the list while downloading', () => {
    // A hole here may be a page that has not arrived yet: the reader must wait on
    // it rather than skip it.
    renderReader({ pages: [1, 3], downloadStatus: 'downloading' })

    turn('ArrowRight')

    expect(shownPage()).toBeNull()
    expect(screen.getByText('reader.pageNotReady')).toBeTruthy()
    expect(counter()).toBe('2 / 2')
  })

  it('still turns one page at a time with contiguous numbering', () => {
    renderReader({ pages: [1, 2, 3] })

    turn('ArrowRight')

    expect(shownPage()).toBe(2)
    expect(counter()).toBe('2 / 3')
  })
})
