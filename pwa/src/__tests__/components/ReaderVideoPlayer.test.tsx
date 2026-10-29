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
import { render, act, fireEvent } from '@testing-library/react'
import VideoPlayer from '../../components/Reader/VideoPlayer'
import type { ReaderImage } from '../../components/Reader/types'
import { THUMB_STRIP_HEIGHT } from '../../components/Reader/layout'

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
  let load: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    observers.length = 0
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver)
    play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    load = vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
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

  // Regression: the controls were anchored 80px up, but the thumbnail strip is
  // taller than that, so the strip covered the bottom of the play/mute buttons.
  // Lifting them further instead left a band of bare video between the two
  // dark surfaces, so they sit exactly on the strip's top edge.
  it('should rest the controls flush on the thumbnail strip while the overlay is visible', () => {
    const { getByLabelText } = render(<VideoPlayer image={video} overlayVisible />)

    const controls = getByLabelText('Seek').parentElement as HTMLElement
    const lift = parseFloat(/(\d+(?:\.\d+)?)px/.exec(controls.style.bottom)?.[1] ?? '0')

    expect(lift).toBe(THUMB_STRIP_HEIGHT)
    expect(controls.style.bottom).toContain('env(safe-area-inset-bottom)')
  })

  it('should keep play, time, the seek bar and mute on a single row', () => {
    const { getByLabelText, getByText } = render(<VideoPlayer image={video} overlayVisible />)

    const row = getByLabelText('Seek').parentElement as HTMLElement
    expect(getByLabelText('Play').parentElement).toBe(row)
    expect(getByText('0:00 / 0:12').parentElement).toBe(row)
    expect(getByLabelText('Unmute').parentElement).toBe(row)
    expect(row.style.flexDirection).not.toBe('column')
    expect(Array.from(row.children).map((child) => child.tagName)).toEqual([
      'BUTTON',
      'SPAN',
      'INPUT',
      'BUTTON',
    ])
  })

  it('should start muted and unmute when the mute button is tapped', () => {
    const { getByLabelText, container } = render(<VideoPlayer image={video} overlayVisible />)
    const element = container.querySelector('video') as HTMLVideoElement
    expect(element.muted).toBe(true)

    fireEvent.click(getByLabelText('Unmute'))

    expect(element.muted).toBe(false)
    expect(getByLabelText('Mute')).toBeTruthy()
  })

  // Regression: webtoon mounts every page, and iOS Safari answers
  // preload="metadata" with a run of Range requests per video. One switch to
  // webtoon on a gallery with 103 videos fetched all of them (1,661 requests,
  // 4.5 GB in two minutes) and froze the tab.
  it('should not give an off-screen player a source so webtoon does not fetch every video', () => {
    const { container } = render(<VideoPlayer image={video} />)

    expect(container.querySelector('video')?.hasAttribute('src')).toBe(false)

    setVisible(true)

    expect(container.querySelector('video')?.getAttribute('src')).toBe(video.url)
  })

  it('should show the thumbnail as poster while an off-screen player has no source', () => {
    const { container } = render(
      <VideoPlayer image={{ ...video, thumbUrl: '/media/thumbs/2b/ff/2bff/thumb_360.webp' }} />,
    )

    expect(container.querySelector('video')?.getAttribute('poster')).toBe(
      '/media/thumbs/2b/ff/2bff/thumb_360.webp',
    )
  })

  it('should drop the source and abort its download when the player scrolls out of view', () => {
    const { container } = render(<VideoPlayer image={video} />)
    setVisible(true)
    load.mockClear()

    setVisible(false)

    expect(container.querySelector('video')?.hasAttribute('src')).toBe(false)
    expect(load).toHaveBeenCalled()
  })

  it('should abort the download when a player with a source unmounts', () => {
    const { container, unmount } = render(<VideoPlayer image={video} />)
    setVisible(true)
    const element = container.querySelector('video') as HTMLVideoElement
    load.mockClear()

    unmount()

    expect(element.hasAttribute('src')).toBe(false)
    expect(load).toHaveBeenCalled()
  })
})
