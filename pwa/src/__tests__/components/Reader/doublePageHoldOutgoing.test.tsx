/**
 * Regression: double-page mode flashed black on every page turn.
 *
 * Each half reused one <img> and swapped its `src`. ReaderImg hides an image
 * until its new src has loaded and decoded (FE-T34), so every turn blanked
 * both halves until the decode settled, even for cached pages. Each half now
 * mounts one element per page, and the outgoing pair stays painted until both
 * incoming pages can be shown.
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DoublePageView } from '@/components/Reader/DoublePageView'
import type { ReaderImage, ReadingDirection } from '@/components/Reader/types'

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

function view(
  left: ReaderImage,
  right: ReaderImage | null,
  onImageLoaded = vi.fn(),
  readingDirection: ReadingDirection = 'ltr',
) {
  return (
    <DoublePageView
      leftImage={left}
      rightImage={right}
      isLoading={false}
      onNext={vi.fn()}
      onPrev={vi.fn()}
      onToggleOverlay={vi.fn()}
      onImageLoaded={onImageLoaded}
      onImageError={vi.fn()}
      scaleMode="fit-both"
      readingDirection={readingDirection}
      showOverlay={false}
      currentPage={left.pageNum}
    />
  )
}

const img = (n: number) => screen.getByAltText(`Page ${n}`) as HTMLImageElement
// Painted = in the layout and not held invisible by ReaderImg.
const painted = (el: HTMLElement) => el.style.display !== 'none' && el.style.visibility !== 'hidden'

describe('DoublePageView holds the outgoing pair', () => {
  it('keeps the outgoing pair painted until both incoming pages have loaded', () => {
    const { rerender } = render(view(page(1), page(2)))
    fireEvent.load(img(1))
    fireEvent.load(img(2))

    rerender(view(page(3), page(4)))

    // The bug: one element per half swapped its src, so pages 1 and 2 were
    // gone and both halves were invisible until the new pages decoded.
    expect(painted(img(1))).toBe(true)
    expect(painted(img(2))).toBe(true)
    expect(painted(img(3))).toBe(false)

    fireEvent.load(img(3))
    expect(painted(img(1))).toBe(true)
    expect(painted(img(3))).toBe(false)

    fireEvent.load(img(4))
    expect(painted(img(3))).toBe(true)
    expect(painted(img(4))).toBe(true)
    expect(screen.queryByAltText('Page 1')).toBeNull()
    expect(screen.queryByAltText('Page 2')).toBeNull()
  })

  it('reports the load again when turning back onto the held pair', () => {
    const onImageLoaded = vi.fn()
    const { rerender } = render(view(page(1), page(2), onImageLoaded))
    fireEvent.load(img(1))
    fireEvent.load(img(2))
    rerender(view(page(3), page(4), onImageLoaded))
    onImageLoaded.mockClear()

    // Pages 1 and 2 never fire `load` again; without the replay the parent
    // spinner would wait forever.
    rerender(view(page(1), page(2), onImageLoaded))

    expect(painted(img(1))).toBe(true)
    expect(painted(img(2))).toBe(true)
    expect(onImageLoaded).toHaveBeenCalled()
  })

  it('swaps to a last page that has no partner once it has loaded', () => {
    const { rerender } = render(view(page(19), page(20)))
    fireEvent.load(img(19))
    fireEvent.load(img(20))

    rerender(view(page(21), null))
    expect(painted(img(19))).toBe(true)

    fireEvent.load(img(21))
    expect(painted(img(21))).toBe(true)
    expect(screen.queryByAltText('Page 20')).toBeNull()
  })

  it('control: does not hold for an incoming video', () => {
    const { rerender } = render(view(page(1), page(2)))
    fireEvent.load(img(1))
    fireEvent.load(img(2))

    rerender(view(page(3, { mediaType: 'video', url: '/media/3.mp4' }), null))

    expect(screen.queryByAltText('Page 1')).toBeNull()
    expect(document.querySelector('video')).not.toBeNull()
  })
})
