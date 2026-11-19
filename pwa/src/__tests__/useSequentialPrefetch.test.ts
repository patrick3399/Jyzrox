/**
 * useSequentialPrefetch — Vitest test suite
 *
 * Tests the prefetch hook used by the Reader component.
 * The hook has two modes:
 *   - Proxy mode: a bounded window sized from page-turn history
 *     (proxyPrefetchPolicy.ts), at most 4 requests in flight, waiting for the
 *     current page first. Page turns keep in-flight prefetches inside the keep
 *     window ([currentPage - behind, currentPage + PREFETCH_KEEP_AHEAD]) instead
 *     of aborting everything, so fast flipping can build a buffer.
 *   - Local mode: LOCAL_PREFETCH_CONCURRENCY (2) slots over a window of 5 ahead +
 *     2 behind, shrunk by a decoded-pixel budget for huge originals
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { PROXY_CURRENT_PAGE_GRACE_MS, useSequentialPrefetch } from '../components/Reader/hooks'
import { SCRUB_QUIET_MS } from '../components/Reader/proxyPrefetchPolicy'
import type { ReaderImage } from '../components/Reader/types'

// ── Fake Image factory ────────────────────────────────────────────────

interface FakeImage {
  src: string
  /** Every non-empty URL ever assigned, kept after cleanup resets `src`. */
  requested: string[]
  onload: (() => void) | null
  onerror: (() => void) | null
  triggerLoad: () => void
  triggerError: () => void
}

function makeFakeImageClass(): {
  FakeImage: new () => FakeImage
  instances: FakeImage[]
} {
  const instances: FakeImage[] = []

  class FakeImage {
    private currentSrc = ''
    requested: string[] = []

    get src() {
      return this.currentSrc
    }

    set src(value: string) {
      if (value) this.requested.push(value)
      this.currentSrc = value
    }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null

    constructor() {
      instances.push(this)
    }

    triggerLoad() {
      this.onload?.()
    }

    triggerError() {
      this.onerror?.()
    }
  }

  return { FakeImage, instances }
}

// ── Helpers ───────────────────────────────────────────────────────────

function makeImages(count: number, startPage = 1): ReaderImage[] {
  return Array.from({ length: count }, (_, i) => ({
    pageNum: startPage + i,
    url: `http://proxy/page/${startPage + i}`,
    isLocal: false,
    mediaType: 'image' as const,
  }))
}

/** Every URL any FakeImage was pointed at, in request order */
function requestedSrcs(instances: FakeImage[]): string[] {
  return instances.flatMap((i) => i.requested)
}

/** Settle in-flight requests one at a time, letting each settle top the window up */
async function settleInFlight(instances: FakeImage[], max = 20): Promise<void> {
  for (let i = 0; i < max; i++) {
    const pending = instances.find((img) => img.src !== '' && img.onload)
    if (!pending) return
    await act(async () => {
      pending.triggerLoad()
    })
  }
}

/** Get all non-empty src values from FakeImage instances */
function activeSrcs(instances: FakeImage[]): string[] {
  return instances.filter((i) => i.src !== '').map((i) => i.src)
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useSequentialPrefetch', () => {
  let instances: FakeImage[]

  beforeEach(() => {
    const { FakeImage, instances: inst } = makeFakeImageClass()
    instances = inst
    vi.stubGlobal('Image', FakeImage)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  // ── Proxy mode ───────────────────────────────────────────────────

  describe('proxy mode', () => {
    it('should request the initial forward window on first render', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      expect(activeSrcs(instances)).toEqual([
        'http://proxy/page/2',
        'http://proxy/page/3',
        'http://proxy/page/4',
      ])
    })

    // Regression: the proxy chain continued with pageNum + 1 after every settle
    // and had no forward limit, so a reader resting on one page pulled the whole
    // gallery from EH (3333614: all 80 remaining pages within 70 s).
    it('should not prefetch past the forward window while the reader rests on one page', async () => {
      const images = makeImages(30)

      renderHook(() => useSequentialPrefetch(images, 1, true))
      await settleInFlight(instances, 30)

      expect(requestedSrcs(instances)).toEqual([
        'http://proxy/page/2',
        'http://proxy/page/3',
        'http://proxy/page/4',
      ])
    })

    it('should not re-request an errored page while the window stays put', async () => {
      const images = makeImages(10)

      const { result } = renderHook(() => useSequentialPrefetch(images, 1, true))

      await act(async () => {
        instances[0].triggerError()
      })

      expect(requestedSrcs(instances).filter((src) => src === 'http://proxy/page/2')).toHaveLength(
        1,
      )
      expect(result.current.has(2)).toBe(true)
      expect(activeSrcs(instances)).toEqual(['http://proxy/page/3', 'http://proxy/page/4'])
    })

    it('should abort the old window and request only the next page after a jump', async () => {
      // A jump from page 1 to page 20 puts every pre-turn request (pages 2-4)
      // outside the keep window ([20, 30]), so all of them get aborted. The
      // reader has not shown which way they will read from page 20, so only
      // page 21 is requested.
      const images = makeImages(30)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      const preTurnInstances = [...instances]

      currentPage = 20
      await act(async () => {
        rerender()
      })

      preTurnInstances.forEach((inst) => {
        expect(inst.src).toBe('')
      })
      expect(activeSrcs(instances)).toEqual(['http://proxy/page/21'])
    })

    it('should not create a duplicate request for a page already in prefetchedRef', async () => {
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      // Complete page 2
      await act(async () => {
        instances[0].triggerLoad()
      })
      const countAfterPage2 = instances.length

      // Trigger page 2 onload again (stale callback)
      await act(async () => {
        instances[0].triggerLoad()
      })

      expect(instances.length).toBe(countAfterPage2)
    })
  })

  // ── Local mode ───────────────────────────────────────────────────

  describe('local mode (capped)', () => {
    it('should start only LOCAL_PREFETCH_CONCURRENCY (2) requests on initial render', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, false))

      expect(activeSrcs(instances)).toEqual(['http://proxy/page/2', 'http://proxy/page/3'])
    })

    it('should top up the window as earlier requests settle until 5 ahead are covered', async () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, false))

      await settleInFlight(instances)

      expect(requestedSrcs(instances)).toEqual([
        'http://proxy/page/2',
        'http://proxy/page/3',
        'http://proxy/page/4',
        'http://proxy/page/5',
        'http://proxy/page/6',
      ])
    })

    it('should prefetch the next surviving page across a hole in page numbers', () => {
      const images = makeImages(20).filter((image) => image.pageNum <= 4 || image.pageNum >= 12)

      renderHook(() => useSequentialPrefetch(images, 4, false))

      expect(activeSrcs(instances)).toEqual(['http://proxy/page/12', 'http://proxy/page/13'])
    })

    it('should fire new requests when currentPage advances', async () => {
      const images = makeImages(10)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, false))

      currentPage = 4
      await act(async () => {
        rerender()
      })

      // Pages 2 and 3 fell behind the new window and were aborted, freeing
      // both slots for the pages right after the new current page.
      expect(activeSrcs(instances)).toEqual(['http://proxy/page/5', 'http://proxy/page/6'])
    })

    it('should prefetch available pages ahead and behind when near the end', async () => {
      const images = makeImages(9)

      renderHook(() => useSequentialPrefetch(images, 8, false))

      await settleInFlight(instances)

      // Forward: only page 9; backward: pages 7 and 6.
      expect(requestedSrcs(instances)).toEqual([
        'http://proxy/page/9',
        'http://proxy/page/7',
        'http://proxy/page/6',
      ])
    })

    it('should prefetch only the next page when original images exceed the pixel budget', async () => {
      // Regression (Reader freeze after leaving a huge gallery): local mode
      // fired 5 forward + 2 backward original-resolution requests at once with
      // no cap. A 5336x8000 (~40 MB) gallery put ~7 such files in flight per
      // page turn on iOS Safari, starving the network and memory badly enough
      // that the next screen never rendered after the user backed out.
      const images = makeImages(10).map((img) => ({ ...img, width: 5336, height: 8000 }))

      renderHook(() => useSequentialPrefetch(images, 3, false))

      await settleInFlight(instances)

      expect(requestedSrcs(instances)).toEqual(['http://proxy/page/4'])
    })

    it('should handle onerror without throwing and still mark page as prefetched', async () => {
      const images = makeImages(5)

      const { result } = renderHook(() => useSequentialPrefetch(images, 1, false))

      await act(async () => {
        instances[0].triggerError()
      })

      expect(result.current.has(2)).toBe(true)
    })
  })

  // ── Edge cases ───────────────────────────────────────────────────

  describe('edge cases', () => {
    it('should do nothing when images array is empty', () => {
      renderHook(() => useSequentialPrefetch([], 1, true))
      expect(instances).toHaveLength(0)
    })

    it('should do nothing when currentPage is already the last page', () => {
      const images = makeImages(5)
      renderHook(() => useSequentialPrefetch(images, 5, true))
      expect(instances).toHaveLength(0)
    })

    it('should return a Set containing the prefetched page numbers', async () => {
      const images = makeImages(3)

      const { result } = renderHook(() => useSequentialPrefetch(images, 1, true))

      expect(result.current).toBeInstanceOf(Set)
      expect(result.current.size).toBe(0)

      await act(async () => {
        instances[0].triggerLoad()
      })

      expect(result.current.has(2)).toBe(true)
    })
  })

  // ── Video pages ──────────────────────────────────────────────────
  // Regression: prefetching a page whose blob is a video pointed an <img> at
  // the .mp4 URL. The decoder can never use those bytes, but the browser still
  // downloads the whole file before firing onerror — a 144 MB video was pulled
  // repeatedly until iOS Safari killed the tab mid-playback.

  describe('video pages', () => {
    it('should not prefetch a video page through an Image element', () => {
      const images = makeImages(6)
      images[2] = { ...images[2], mediaType: 'video', url: 'http://proxy/page/3.mp4' }

      renderHook(() => useSequentialPrefetch(images, 1, false))

      expect(instances.map((i) => i.src)).not.toContain('http://proxy/page/3.mp4')
    })

    it('should keep prefetching later image pages when a video page is skipped', async () => {
      const images = makeImages(6)
      images[1] = { ...images[1], mediaType: 'video', url: 'http://proxy/page/2.mp4' }

      renderHook(() => useSequentialPrefetch(images, 1, false))
      await settleInFlight(instances)

      const srcs = requestedSrcs(instances)
      expect(srcs).not.toContain('http://proxy/page/2.mp4')
      expect(srcs).toContain('http://proxy/page/3')
      expect(srcs).toContain('http://proxy/page/6')
    })

    it('should advance the proxy chain past a video page instead of stalling on it', async () => {
      const images = makeImages(5)
      images[1] = { ...images[1], mediaType: 'video', url: 'http://proxy/page/2.mp4' }

      renderHook(() => useSequentialPrefetch(images, 1, true))

      // Concurrency is 4: with page 2 skipped, the available slots must land on real images.
      const srcs = activeSrcs(instances)
      expect(srcs).not.toContain('http://proxy/page/2.mp4')
      expect(srcs).toContain('http://proxy/page/3')
      expect(srcs).toContain('http://proxy/page/4')
    })
  })

  // ── Re-render stability ──────────────────────────────────────────
  // Regression: Reader rebuilds its `images` array on every render, so the
  // prefetch effect re-ran on every render — including the renders this hook
  // itself triggers when a prefetch settles. Each re-run aborted and re-issued
  // every in-flight request, multiplying one page turn into many concurrent
  // downloads of the same file.

  describe('re-render stability', () => {
    it('should not re-issue in-flight requests when the images array identity changes', async () => {
      let images = makeImages(10)

      const { rerender } = renderHook(() => useSequentialPrefetch(images, 1, false))

      const initialCount = instances.length
      expect(initialCount).toBe(2)

      // Same pages, new array identity — exactly what a Reader re-render produces.
      images = makeImages(10)
      await act(async () => {
        rerender()
      })

      expect(instances).toHaveLength(initialCount)
    })

    it('should prefetch pages that gain a url after a later render', async () => {
      // Reader rebuilds the array every render, so a page that was still
      // downloading (url === null) must still be picked up once it resolves.
      const withoutPage2 = (): ReaderImage[] =>
        makeImages(4).map((img) => (img.pageNum === 2 ? { ...img, url: null } : img))

      let images = withoutPage2()
      const { rerender } = renderHook(() => useSequentialPrefetch(images, 1, false))

      expect(activeSrcs(instances)).not.toContain('http://proxy/page/2')

      // The download finished and page 2 now resolves to a real URL.
      images = makeImages(4)
      await act(async () => {
        rerender()
      })

      // Pages 3 and 4 hold both local slots; page 2 starts as soon as one frees.
      await settleInFlight(instances, 1)

      expect(activeSrcs(instances)).toContain('http://proxy/page/2')
    })
  })

  // ── Windowed page-turn cleanup ─────────────────────────────────────
  // Regression: page turns used to blanket-abort every in-flight prefetch via
  // cleanupAllImages(), throwing away a buffer that was still being built. The
  // fix aborts only requests outside [currentPage, currentPage +
  // PREFETCH_KEEP_AHEAD] (=10); requests inside the window survive the turn.
  // The abort half is still required — without it, a long fast flip would keep
  // growing the window forever and regress FE-T16's memory incident.

  describe('windowed page-turn cleanup', () => {
    it('should abort a prefetch outside the keep-ahead window on page turn but not one inside it', async () => {
      const images = makeImages(20)
      let currentPage = 1

      const { result, rerender } = renderHook(() =>
        useSequentialPrefetch(images, currentPage, true),
      )

      // The initial window puts pages 2, 3 and 4 in flight.
      expect(instances).toHaveLength(3)
      const page2Image = instances[0]
      const page3Image = instances[1]

      // Turn to page 3: keep window becomes [3, 13]. Page 2 falls outside it;
      // page 3 stays inside it.
      currentPage = 3
      await act(async () => {
        rerender()
      })

      // Outside the window: aborted — handlers detached and src reset.
      expect(page2Image.src).toBe('')
      // Inside the window: left running, untouched.
      expect(page3Image.src).toBe('http://proxy/page/3')

      // The kept-alive prefetch must still settle normally afterwards.
      await act(async () => {
        page3Image.triggerLoad()
      })
      expect(result.current.has(3)).toBe(true)
    })
  })

  // ── Epoch bookkeeping survival ──────────────────────────────────────
  // Regression: the onload/onerror handler used to bail out entirely
  // (`if (... || capturedEpoch !== epochRef.current) return`) before recording
  // the page as prefetched whenever a page turn had bumped the epoch since the
  // request started. That dropped legitimately-downloaded bytes from
  // `prefetched` bookkeeping and could cause a pointless later re-request.

  describe('epoch bookkeeping survival', () => {
    it('should record a prefetch in the returned set even when it settles after a page turn', async () => {
      const images = makeImages(20)
      let currentPage = 1

      const { result, rerender } = renderHook(() =>
        useSequentialPrefetch(images, currentPage, true),
      )

      // Page 2's request started under the old epoch, before any page turn.
      const page2Image = instances[0]

      // Turn to page 2: keep window [2, 12] keeps page 2 alive (not aborted),
      // but the epoch has still been bumped.
      currentPage = 2
      await act(async () => {
        rerender()
      })
      expect(page2Image.src).toBe('http://proxy/page/2') // not aborted

      // The pre-turn request for page 2 finally settles, after the epoch bump.
      await act(async () => {
        page2Image.triggerLoad()
      })

      expect(result.current.has(2)).toBe(true)
    })
  })

  // ── No stall after a page turn ───────────────────────────────────────
  // Regression: if every concurrency slot is occupied by requests that started
  // before a page turn and none of them fall outside the keep-ahead window (so
  // none get aborted), no new prefetchPage call can start immediately — they
  // all hit the `inflightCountRef.current >= PROXY_PREFETCH_CONCURRENCY` guard.
  // The chain must not go idle forever in this state: once those pre-turn
  // requests settle, the slot they free up must be used to start a new request
  // that re-enters the chain at (currentPage + 1) and hops forward past
  // whatever is still in flight. This requires BOTH accurate inflightCountRef
  // decrementing AND epoch-independent chain continuation — a partial port of
  // the windowed-cleanup fix that keeps the old early-return-on-epoch-mismatch
  // reproduces the stall this test pins.

  describe('no stall after a page turn', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      vi.setSystemTime(0)
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('should use a freed slot for the window once pre-turn in-flight requests settle', async () => {
      const images = makeImages(30)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      // A brisk forward reader (one page every 400 ms) earns a window wider than
      // the concurrency cap, so every slot is busy after the third turn.
      for (const page of [2, 3, 4]) {
        await act(async () => {
          vi.advanceTimersByTime(400)
          currentPage = page
          rerender()
        })
      }
      const inFlight = activeSrcs(instances)
      expect(inFlight).toHaveLength(4)

      // Settles after a realistic EH fetch time, so the window keeps its width.
      const settling = instances.find((inst) => inst.src === inFlight[0])
      await act(async () => {
        vi.advanceTimersByTime(1_500)
        settling?.triggerLoad()
      })

      // The freed slot goes to the first window page nobody is fetching yet.
      const after = activeSrcs(instances)
      expect(after).toHaveLength(4)
      const highest = (srcs: string[]) =>
        Math.max(...srcs.map((src) => Number(src.split('/').pop())))
      expect(highest(after)).toBe(highest(inFlight) + 1)
    })
  })

  // ── Adaptive proxy window ────────────────────────────────────────────
  // The proxy window follows how the reader moves: a jump fetches only the next
  // page, a scrub fetches nothing until it stops, paging backwards fetches
  // behind, and nothing competes with the current page until it has loaded.

  describe('adaptive proxy window', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      vi.setSystemTime(0)
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('should hold proxy prefetch until the current page is ready', async () => {
      const images = makeImages(10)
      let ready = false

      const { rerender } = renderHook(() =>
        useSequentialPrefetch(images, 1, true, { currentPageReady: ready }),
      )
      expect(instances).toHaveLength(0)

      ready = true
      await act(async () => {
        rerender()
      })
      expect(activeSrcs(instances)).toEqual([
        'http://proxy/page/2',
        'http://proxy/page/3',
        'http://proxy/page/4',
      ])
    })

    it('should start proxy prefetch after the grace period when the current page never reports ready', async () => {
      // A video page, or an image still retrying, may never report ready.
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, true, { currentPageReady: false }))
      expect(instances).toHaveLength(0)

      await act(async () => {
        vi.advanceTimersByTime(PROXY_CURRENT_PAGE_GRACE_MS)
      })
      expect(activeSrcs(instances)).toHaveLength(3)
    })

    it('should not start proxy prefetches while the reader scrubs through pages', async () => {
      const images = makeImages(40)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      const turnTo = async (page: number) => {
        await act(async () => {
          vi.advanceTimersByTime(100)
          currentPage = page
          rerender()
        })
      }

      // Dragging across pages 10..14, 100 ms apart. The first two turns cannot
      // be told apart from a jump and a step yet; from the third on it is a drag.
      await turnTo(10)
      await turnTo(11)
      const beforeDrag = instances.length
      for (const page of [12, 13, 14]) await turnTo(page)
      expect(instances).toHaveLength(beforeDrag)

      // Once the drag rests, only the page after where it stopped is fetched.
      await act(async () => {
        vi.advanceTimersByTime(SCRUB_QUIET_MS)
      })
      expect(requestedSrcs(instances.slice(beforeDrag))).toEqual(['http://proxy/page/15'])
    })

    it('should prefetch behind the current page while the reader pages backwards', async () => {
      const images = makeImages(40)
      let currentPage = 30

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      for (const page of [29, 28, 27]) {
        await act(async () => {
          vi.advanceTimersByTime(2_000)
          currentPage = page
          rerender()
        })
      }

      const active = activeSrcs(instances)
      expect(active).toContain('http://proxy/page/26')
      expect(active).toContain('http://proxy/page/25')
      expect(active.some((src) => Number(src.split('/').pop()) > 27)).toBe(false)
    })
  })
})
