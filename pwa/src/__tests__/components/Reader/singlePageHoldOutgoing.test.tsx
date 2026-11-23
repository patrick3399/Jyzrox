/**
 * Regression: in the E-Hentai online viewer every first visit to a page flashed
 * black between pages.
 *
 * ReaderImg keeps a paged image invisible until it has loaded and decoded
 * (FE-T34). Proxy mode never pre-mounts the next page (FE-T20), so each turn
 * mounted a new, still-invisible element while the outgoing page was already
 * hidden: the screen showed the black background until the decode settled.
 * The single-page view now keeps the outgoing page painted until the incoming
 * one can be shown.
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SinglePageView } from '@/components/Reader/SinglePageView'
import type { ReaderImage } from '@/components/Reader/types'

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

beforeAll(() => {
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
  HTMLMediaElement.prototype.pause = vi.fn()
})

function page(pageNum: number, overrides: Partial<ReaderImage> = {}): ReaderImage {
  return {
    pageNum,
    url: `/api/eh/image-proxy/123/${pageNum}`,
    isLocal: false,
    width: 1280,
    height: 1810,
    mediaType: 'image',
    ...overrides,
  }
}

const NO_PAGES: ReadonlySet<number> = new Set()

function view(image: ReaderImage, prevImage: ReaderImage | null, nextImage: ReaderImage | null) {
  return (
    <SinglePageView
      image={image}
      prevImage={prevImage}
      nextImage={nextImage}
      prefetchedPages={NO_PAGES}
      isLoading={false}
      onNext={vi.fn()}
      onPrev={vi.fn()}
      onToggleOverlay={vi.fn()}
      onImageLoaded={vi.fn()}
      onImageError={vi.fn()}
      scaleMode="fit-both"
      readingDirection="ltr"
      showOverlay={false}
      currentPage={image.pageNum}
    />
  )
}

const img = (n: number) => screen.getByAltText(`Page ${n}`) as HTMLImageElement
// Painted = in the layout and not held invisible by ReaderImg.
const painted = (el: HTMLElement) => el.style.display !== 'none' && el.style.visibility !== 'hidden'

describe('SinglePageView holds the outgoing page', () => {
  it('keeps the outgoing page painted until a not yet mounted page has loaded', () => {
    const { rerender } = render(view(page(1), null, page(2)))
    fireEvent.load(img(1))
    expect(painted(img(1))).toBe(true)

    rerender(view(page(2), page(1), page(3)))

    // The bug: page 1 was hidden at once while page 2 was still invisible.
    expect(painted(img(1))).toBe(true)
    expect(painted(img(2))).toBe(false)

    fireEvent.load(img(2))

    expect(painted(img(2))).toBe(true)
    expect(img(1).style.display).toBe('none')
  })

  it('keeps the outgoing page through a jump outside its neighbours', () => {
    const { rerender } = render(view(page(1), null, page(2)))
    fireEvent.load(img(1))

    rerender(view(page(10), page(9), page(11)))

    expect(painted(img(1))).toBe(true)
    fireEvent.load(img(10))
    expect(painted(img(10))).toBe(true)
    expect(screen.queryByAltText('Page 1')).toBeNull()
  })

  it('shows the failure notice once the incoming page gives up', () => {
    const local = (n: number) => page(n, { url: `/media/cas/${n}.jpg`, isLocal: true })
    const { rerender } = render(view(local(1), null, local(2)))
    fireEvent.load(img(1))

    rerender(view(local(2), local(1), local(3)))
    fireEvent.error(img(2))

    expect(screen.getByText('reader.imageLoadFailed')).toBeTruthy()
    expect(img(1).style.display).toBe('none')
  })

  it('control: does not hold for an incoming video', () => {
    const { rerender } = render(view(page(1), null, null))
    fireEvent.load(img(1))

    rerender(view(page(2, { mediaType: 'video', url: '/media/2.mp4' }), page(1), null))

    expect(img(1).style.display).toBe('none')
  })
})
