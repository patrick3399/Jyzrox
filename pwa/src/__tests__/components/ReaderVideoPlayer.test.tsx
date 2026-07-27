/**
 * VideoPlayer — Vitest test suite
 *
 * Regression cover for the iOS Safari crash while playing a video in the
 * Reader: every mounted player used `autoPlay` with the browser's default
 * preload, so webtoon mode started buffering every video in the loaded page
 * list at once. A single gallery holding a 144 MB clip was enough to exhaust
 * the tab's memory mid-playback.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@testing-library/react'
import VideoPlayer from '../../components/Reader/VideoPlayer'
import type { ReaderImage } from '../../components/Reader/types'

// ── IntersectionObserver stub ─────────────────────────────────────────

type ObserverCallback = (entries: { isIntersecting: boolean }[]) => void

interface ObserverEntry {
  callback: ObserverCallback
  options?: IntersectionObserverInit
  disconnected: boolean
}

const observers: ObserverEntry[] = []

class FakeIntersectionObserver {
  private entry: ObserverEntry

  constructor(callback: ObserverCallback, options?: IntersectionObserverInit) {
    this.entry = { callback, options, disconnected: false }
    observers.push(this.entry)
  }

  observe() {}
  unobserve() {}
  disconnect() {
    this.entry.disconnected = true
  }
}

/** Drive the most recently created observer. */
function setVisible(isIntersecting: boolean) {
  const live = observers.filter((o) => !o.disconnected)
  const target = live[live.length - 1]
  act(() => {
    target.callback([{ isIntersecting }])
  })
}

const video: ReaderImage = {
  pageNum: 1,
  url: '/media/cas/2b/ff/2bff.mp4',
  isLocal: true,
  mediaType: 'video',
  duration: 12,
}

describe('VideoPlayer', () => {
  let play: ReturnType<typeof vi.spyOn>
  let pause: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    observers.length = 0
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver)
    play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('should never ask the browser to preload the full video body', () => {
    const { container } = render(<VideoPlayer image={video} />)

    const el = container.querySelector('video')
    expect(el?.getAttribute('preload')).toBe('metadata')
  })

  it('should not autoplay on mount so offscreen players do not all buffer at once', () => {
    const { container } = render(<VideoPlayer image={video} />)

    expect(container.querySelector('video')?.hasAttribute('autoplay')).toBe(false)
    expect(play).not.toHaveBeenCalled()
  })

  it('should start playback once the player scrolls into view', () => {
    render(<VideoPlayer image={video} />)

    setVisible(true)

    expect(play).toHaveBeenCalled()
  })

  it('should treat any visible part as visible so a taller-than-viewport video still plays', () => {
    // A fractional threshold is measured against the element, not the viewport:
    // a video taller than the screen never reaches it even while it fills the
    // screen, and would then never start.
    render(<VideoPlayer image={video} />)

    expect(observers[observers.length - 1].options?.threshold ?? 0).toBe(0)
  })

  it('should pause playback when the player scrolls out of view', () => {
    render(<VideoPlayer image={video} />)

    setVisible(true)
    setVisible(false)

    expect(pause).toHaveBeenCalled()
  })

  it('should not reject unhandled when the browser refuses autoplay', async () => {
    play.mockRejectedValue(new DOMException('NotAllowedError'))
    render(<VideoPlayer image={video} />)

    setVisible(true)
    await act(async () => {
      await Promise.resolve()
    })

    expect(play).toHaveBeenCalled()
  })
})
