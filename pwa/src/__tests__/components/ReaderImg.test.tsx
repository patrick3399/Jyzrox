/**
 * Regression tests for ReaderImg error handling.
 *
 * Bug 1: MediaElement's <img> had onLoad but no onError, so a failed remote
 * image never cleared pageLoading (infinite spinner) and rendered the native
 * broken-image icon.
 *
 * Bug 2: the failure placeholder latched permanently on the FIRST error. In EH
 * proxy mode a direct page jump races the paginated token fetch — the
 * image-proxy 404s transiently until tokens land in Redis — so the reader must
 * auto-retry with backoff and only latch the failure UI once retries are
 * exhausted. Before this fix, a jump showed "image failed to load" forever
 * even though the image became available seconds later.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ReaderImg } from '@/components/Reader'
import type { ReaderImage } from '@/components/Reader/types'

const img: ReaderImage = {
  pageNum: 1,
  url: '/api/eh/image-proxy/1/1',
  isLocal: false,
  mediaType: 'image',
}

// Contract: auto-retry backoff schedule (ms). Must match ReaderImg.
const AUTO_RETRY_DELAYS_MS = [1000, 2000, 3000, 5000, 8000]

/** Drive the component through all auto-retries, failing each attempt. */
function exhaustAutoRetries(alt: string) {
  for (const delay of AUTO_RETRY_DELAYS_MS) {
    fireEvent.error(screen.getByAltText(alt))
    act(() => {
      vi.advanceTimersByTime(delay)
    })
  }
  // Final (budget-exhausted) attempt fails too.
  fireEvent.error(screen.getByAltText(alt))
}

describe('ReaderImg transient error auto-retry', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('auto-retries with a cache-busted src after a load error instead of latching the failure placeholder (EH proxy token race)', () => {
    const onError = vi.fn()
    const onLoad = vi.fn()
    render(<ReaderImg image={img} onError={onError} onLoad={onLoad} />)

    fireEvent.error(screen.getByAltText('Page 1'))

    // Not terminal: no retry button, parent spinner not resolved.
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(onError).not.toHaveBeenCalled()
    // A waiting placeholder replaces the broken <img> during the backoff.
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByAltText('Page 1')).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(AUTO_RETRY_DELAYS_MS[0])
    })

    // Retry attempt: <img> remounted with a cache-busted src.
    const el = screen.getByAltText('Page 1') as HTMLImageElement
    expect(el.src).toContain('_r=1')

    // The retry succeeds → image shows, parent onLoad fires, no failure UI.
    fireEvent.load(el)
    expect(onLoad).toHaveBeenCalledTimes(1)
    expect(onError).not.toHaveBeenCalled()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows the failure placeholder and notifies the parent only after auto-retries are exhausted', () => {
    const onError = vi.fn()
    const onLoad = vi.fn()
    render(<ReaderImg image={img} onError={onError} onLoad={onLoad} />)

    exhaustAutoRetries('Page 1')

    expect(onError).toHaveBeenCalledTimes(1)
    expect(onLoad).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(screen.queryByAltText('Page 1')).not.toBeInTheDocument()
  })

  it('manual retry after exhaustion restarts loading with a fresh auto-retry budget', () => {
    render(<ReaderImg image={img} />)
    exhaustAutoRetries('Page 1')

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    const el = screen.getByAltText('Page 1') as HTMLImageElement
    expect(el).toBeInTheDocument()

    // Fresh budget: the next error auto-retries again instead of failing outright.
    fireEvent.error(el)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('a url change during the retry wait cancels the pending retry and resets state', () => {
    const { rerender } = render(<ReaderImg image={img} />)
    fireEvent.error(screen.getByAltText('Page 1'))
    expect(screen.getByRole('status')).toBeInTheDocument()

    const next: ReaderImage = { ...img, pageNum: 2, url: '/api/eh/image-proxy/1/2' }
    rerender(<ReaderImg image={next} />)

    // New page renders its plain (non-cache-busted) url immediately.
    const el = screen.getByAltText('Page 2') as HTMLImageElement
    expect(el.src).toContain('/api/eh/image-proxy/1/2')
    expect(el.src).not.toContain('_r=')

    // The stale timer must not fire a cache-busted reload of the old attempt.
    act(() => {
      vi.advanceTimersByTime(60000)
    })
    expect((screen.getByAltText('Page 2') as HTMLImageElement).src).not.toContain('_r=')
  })
})

describe('ReaderImg has no thumbhash blur-up placeholder (perf/UX regression)', () => {
  // The reader used to paint the decoded thumbhash as a `background-size: cover`
  // background behind the object-contain <img>. In the letterbox margins of a
  // portrait page that upscaled ~32px hash bled through as colored fringes, and
  // decoding it added per-page work on every turn. The reader must now render
  // the page image plainly, with no background placeholder — even when the
  // image carries a thumbhash.
  it('never paints a background even when the image carries a thumbhash', () => {
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
    expect(el.style.backgroundImage === '' || el.style.backgroundImage === 'none').toBe(true)
  })

  it('passes the caller style through untouched (no injected aspect-ratio/background)', () => {
    const noHash: ReaderImage = {
      pageNum: 3,
      url: '/media/cas/aa/bb/y.jpg',
      isLocal: true,
      width: 800,
      height: 1200,
      mediaType: 'image',
    }
    render(<ReaderImg image={noHash} style={{ maxWidth: '500px' }} />)
    const el = screen.getByAltText('Page 3') as HTMLImageElement
    expect(el.style.backgroundImage === '' || el.style.backgroundImage === 'none').toBe(true)
    expect(el.style.aspectRatio === '' || el.style.aspectRatio === 'auto').toBe(true)
    expect(el.style.maxWidth).toBe('500px')
  })
})
