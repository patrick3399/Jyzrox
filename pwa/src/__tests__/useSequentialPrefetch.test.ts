/**
 * useSequentialPrefetch — Vitest test suite
 *
 * Tests the prefetch hook used by the Reader component.
 * The hook has two modes:
 *   - Proxy mode: PROXY_PREFETCH_CONCURRENCY (4) concurrent slots with chaining.
 *     Page turns keep in-flight prefetches inside a window ahead of the current
 *     page ([currentPage, currentPage + PREFETCH_KEEP_AHEAD]) instead of aborting
 *     everything, so fast flipping can build a buffer.
 *   - Local mode: fire up to 3 concurrent requests per page change
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSequentialPrefetch } from '../components/Reader/hooks'
import type { ReaderImage } from '../components/Reader/types'

// ── Fake Image factory ────────────────────────────────────────────────

interface FakeImage {
  src: string
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
    src = ''
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
    it('should create 4 in-flight Image requests on initial render (concurrency=4)', () => {
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      expect(instances).toHaveLength(4)
      expect(instances[0].src).toBe('http://proxy/page/2')
      expect(instances[1].src).toBe('http://proxy/page/3')
      expect(instances[2].src).toBe('http://proxy/page/4')
      expect(instances[3].src).toBe('http://proxy/page/5')
    })

    it('should NOT start more than 4 requests while all four are in flight', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      expect(instances).toHaveLength(4)
    })

    it('should eventually prefetch all remaining pages after completing initial ones', async () => {
      const images = makeImages(5)

      const { result } = renderHook(() => useSequentialPrefetch(images, 1, true))

      // Complete all in-flight images until chain settles
      for (let i = 0; i < 20 && instances.some((inst) => inst.onload); i++) {
        const pending = instances.find((inst) => inst.onload)
        if (!pending) break
        await act(async () => {
          pending.triggerLoad()
        })
      }

      // All pages 2-5 should be prefetched
      expect(result.current.has(2)).toBe(true)
      expect(result.current.has(3)).toBe(true)
      expect(result.current.has(4)).toBe(true)
      expect(result.current.has(5)).toBe(true)
    })

    it('should continue the chain (not stall) when an image errors', async () => {
      const images = makeImages(5)

      const { result: _result } = renderHook(() => useSequentialPrefetch(images, 1, true))

      // Error page 2
      await act(async () => {
        instances[0].triggerError()
      })

      // The chain should have spawned at least one more request
      expect(instances.length).toBeGreaterThan(2)
    })

    it('should abort out-of-window prefetches and start a new window when currentPage jumps far ahead', async () => {
      // Page turns no longer restart the chain by aborting everything — they keep
      // in-flight prefetches inside [currentPage, currentPage + PREFETCH_KEEP_AHEAD]
      // (= 10) and only abort requests that fall outside it. A jump from page 1 to
      // page 20 puts every pre-turn request (pages 2-5) outside the new window
      // ([20, 30]), so — unlike a small in-window turn — all of them get aborted
      // and a fresh window is started from the new position.
      const images = makeImages(30)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      expect(instances).toHaveLength(4)
      const preTurnInstances = [...instances]

      // User jumps to page 20 — far outside the old keep-ahead window.
      currentPage = 20
      await act(async () => {
        rerender()
      })

      // Every pre-turn request must have been aborted (src reset).
      preTurnInstances.forEach((inst) => {
        expect(inst.src).toBe('')
      })

      // A new window of 4 requests must have been started from page 21.
      const srcs = activeSrcs(instances)
      expect(srcs).toContain('http://proxy/page/21')
      expect(srcs).toContain('http://proxy/page/22')
      expect(srcs).toContain('http://proxy/page/23')
      expect(srcs).toContain('http://proxy/page/24')
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

  describe('local mode (concurrent)', () => {
    it('should fire up to 5 concurrent forward Image requests on initial render', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, false))

      // 5 forward (pages 2-6) + 0 backward (page 0 and below are out of bounds)
      expect(instances).toHaveLength(5)
      const srcs = instances.map((i) => i.src)
      expect(srcs).toContain('http://proxy/page/2')
      expect(srcs).toContain('http://proxy/page/3')
      expect(srcs).toContain('http://proxy/page/4')
      expect(srcs).toContain('http://proxy/page/5')
      expect(srcs).toContain('http://proxy/page/6')
    })

    it('should NOT wait for earlier requests to complete before firing all requests', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, false))

      const initialCount = instances.length
      act(() => {
        instances[0].triggerLoad()
      })
      // Local mode is fire-and-forget: no new requests from onload
      expect(instances).toHaveLength(initialCount)
    })

    it('should fire new requests when currentPage advances', async () => {
      const images = makeImages(10)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, false))

      currentPage = 4
      await act(async () => {
        rerender()
      })

      const srcs = instances.map((i) => i.src)
      expect(srcs).toContain('http://proxy/page/5')
      expect(srcs).toContain('http://proxy/page/6')
      expect(srcs).toContain('http://proxy/page/7')
    })

    it('should prefetch available pages ahead and behind when near the end', () => {
      const images = makeImages(9)
      const currentPage = 8

      renderHook(() => useSequentialPrefetch(images, currentPage, false))

      // Forward: only page 9 (1 page)
      // Backward: pages 7 and 6 (2 pages)
      // Total: 3 instances
      expect(instances).toHaveLength(3)
      const srcs = instances.map((i) => i.src)
      expect(srcs).toContain('http://proxy/page/9')
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

    it('should keep prefetching later image pages when a video page is skipped', () => {
      const images = makeImages(6)
      images[1] = { ...images[1], mediaType: 'video', url: 'http://proxy/page/2.mp4' }

      renderHook(() => useSequentialPrefetch(images, 1, false))

      const srcs = instances.map((i) => i.src)
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
      expect(initialCount).toBe(5)

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

      const { result, rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      // Concurrency 4: initial in-flight requests are for pages 2, 3, 4, 5.
      expect(instances).toHaveLength(4)
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

      const { result, rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

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
    it('should issue a new prefetch once pre-turn in-flight requests settle even though all slots were full at the turn', async () => {
      const images = makeImages(10)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      // Concurrency 4: pages 2, 3, 4, 5 occupy every slot.
      expect(instances).toHaveLength(4)
      const page2Image = instances[0]

      // Small turn to page 2: keep window [2, 12] keeps pages 2-5 all alive, so
      // nothing is aborted and every concurrency slot stays occupied.
      currentPage = 2
      await act(async () => {
        rerender()
      })
      // No slot was freed by the turn itself, so no new request could start yet.
      expect(instances).toHaveLength(4)

      // One of the pre-turn requests (page 2) finally settles.
      await act(async () => {
        page2Image.triggerLoad()
      })

      // The freed slot must be used: the chain re-enters at currentPage+1 (=3)
      // and hops forward past pages 3, 4, 5 (still in flight) to land on the
      // first genuinely available page, 6.
      expect(instances).toHaveLength(5)
      expect(instances[4].src).toBe('http://proxy/page/6')
    })
  })
})
