/**
 * Regression: the first page of the Reader stuck as a low-resolution mosaic on
 * iOS (standalone PWA).
 *
 * nginx served the whole file and the <img> fired `load`, yet the page kept
 * showing the frame WebKit decoded while the bytes were still arriving — an
 * early progressive-JPEG scan, or only the top part of a baseline JPEG.
 * Pinching (a CSS transform) and turning away and back reused that frame.
 * Only the page on screen during its download was ever painted from partial
 * data: every later page is fetched by the prefetcher's detached Image first.
 *
 * The paged views therefore keep the <img> invisible until it has loaded and
 * decoded, so nothing is painted from an incomplete download.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ReaderImg } from '@/components/Reader'
import type { ReaderImage } from '@/components/Reader/types'

const page: ReaderImage = {
  pageNum: 1,
  url: '/media/cas/c5/2d/c52d.jpg',
  isLocal: true,
  width: 1536,
  height: 2048,
  mediaType: 'image',
}

function deferred() {
  let resolve!: () => void
  let reject!: (e: Error) => void
  const promise = new Promise<void>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function stubDecode(impl: () => Promise<void>) {
  Object.defineProperty(HTMLImageElement.prototype, 'decode', {
    configurable: true,
    writable: true,
    value: vi.fn(impl),
  })
}

afterEach(() => {
  delete (HTMLImageElement.prototype as { decode?: unknown }).decode
})

describe('ReaderImg reveal after decode', () => {
  it('keeps the page image invisible while its bytes are still arriving', () => {
    render(<ReaderImg image={page} />)
    expect((screen.getByAltText('Page 1') as HTMLImageElement).style.visibility).toBe('hidden')
  })

  it('stays invisible after load until decode settles, then reveals and reports the load', async () => {
    const decode = deferred()
    stubDecode(() => decode.promise)
    const onLoad = vi.fn()
    render(<ReaderImg image={page} onLoad={onLoad} />)
    const el = screen.getByAltText('Page 1') as HTMLImageElement

    fireEvent.load(el)
    expect(el.style.visibility).toBe('hidden')
    expect(onLoad).not.toHaveBeenCalled()

    await act(async () => {
      decode.resolve()
      await decode.promise
    })

    expect(el.style.visibility).toBe('')
    expect(onLoad).toHaveBeenCalledTimes(1)
  })

  it('reveals the image even when decode() rejects', async () => {
    const decode = deferred()
    stubDecode(() => decode.promise)
    const onLoad = vi.fn()
    render(<ReaderImg image={page} onLoad={onLoad} />)
    const el = screen.getByAltText('Page 1') as HTMLImageElement

    fireEvent.load(el)
    await act(async () => {
      decode.reject(new Error('EncodingError'))
      await decode.promise.catch(() => undefined)
    })

    expect(el.style.visibility).toBe('')
    expect(onLoad).toHaveBeenCalledTimes(1)
  })

  it('hides the image again when the page url changes', () => {
    const { rerender } = render(<ReaderImg image={page} />)
    fireEvent.load(screen.getByAltText('Page 1'))
    expect((screen.getByAltText('Page 1') as HTMLImageElement).style.visibility).toBe('')

    rerender(<ReaderImg image={{ ...page, url: '/media/cas/01/dc/01dc.jpg' }} />)

    expect((screen.getByAltText('Page 1') as HTMLImageElement).style.visibility).toBe('hidden')
  })

  it('leaves lazily loaded (webtoon) images visible from the start', () => {
    render(<ReaderImg image={page} loading="lazy" />)
    expect((screen.getByAltText('Page 1') as HTMLImageElement).style.visibility).toBe('')
  })

  it('keeps the caller style while hidden', () => {
    render(<ReaderImg image={page} style={{ display: 'none' }} />)
    const el = screen.getByAltText('Page 1') as HTMLImageElement
    expect(el.style.display).toBe('none')
    expect(el.style.visibility).toBe('hidden')
  })
})
