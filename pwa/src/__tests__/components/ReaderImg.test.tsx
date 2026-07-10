/**
 * Regression: a Reader image whose <img> fires onError must NOT leave the
 * caller's loading spinner spinning forever, and must show a retry placeholder
 * instead of the browser's broken-image icon.
 *
 * Bug: MediaElement's <img> had onLoad but no onError, so a failed remote image
 * never cleared pageLoading (infinite spinner) and rendered the native broken icon.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ReaderImg } from '@/components/Reader'
import type { ReaderImage } from '@/components/Reader/types'

// useThumbhash relies on a Worker; stub it with a controllable map.
const thumbhashMap = new Map<string, string | null>()
vi.mock('@/hooks/useThumbhash', () => ({
  useThumbhash: (hashes: string[]) => {
    const m = new Map<string, string | null>()
    for (const h of hashes) if (thumbhashMap.has(h)) m.set(h, thumbhashMap.get(h) ?? null)
    return m
  },
}))

const img: ReaderImage = {
  pageNum: 1,
  url: '/api/eh/image-proxy/1/1',
  isLocal: false,
  mediaType: 'image',
}

describe('ReaderImg onError', () => {
  it('calls onError and shows a retry control when the image fails to load', () => {
    const onError = vi.fn()
    const onLoad = vi.fn()
    render(<ReaderImg image={img} onError={onError} onLoad={onLoad} />)

    const el = screen.getByAltText('Page 1')
    fireEvent.error(el)

    expect(onError).toHaveBeenCalledTimes(1)
    expect(onLoad).not.toHaveBeenCalled()
    // The broken <img> is replaced by a retry placeholder.
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(screen.queryByAltText('Page 1')).not.toBeInTheDocument()
  })

  it('retry restores the image element', () => {
    render(<ReaderImg image={img} />)
    fireEvent.error(screen.getByAltText('Page 1'))
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(screen.getByAltText('Page 1')).toBeInTheDocument()
  })
})

describe('ReaderImg blur-up', () => {
  it('paints the decoded thumbhash as background until the image loads, then clears it on load', () => {
    thumbhashMap.set('HASH', 'data:image/png;base64,PLACEHOLDER')
    const withHash: ReaderImage = {
      pageNum: 2,
      url: '/media/cas/aa/bb/x.jpg',
      isLocal: true,
      width: 800,
      height: 1200,
      mediaType: 'image',
      thumbhash: 'HASH',
    }
    render(<ReaderImg image={withHash} />)
    const el = screen.getByAltText('Page 2') as HTMLImageElement
    expect(el.style.backgroundImage).toContain('PLACEHOLDER')

    fireEvent.load(el)
    expect(el.style.backgroundImage).toBe('')
  })

  it('renders no placeholder background when thumbhash is absent', () => {
    const noHash: ReaderImage = {
      pageNum: 3,
      url: '/media/cas/aa/bb/y.jpg',
      isLocal: true,
      mediaType: 'image',
    }
    render(<ReaderImg image={noHash} />)
    const el = screen.getByAltText('Page 3') as HTMLImageElement
    expect(el.style.backgroundImage === '' || el.style.backgroundImage === 'none').toBe(true)
  })
})
