/**
 * useSequentialPrefetch — Vitest test suite
 *
 * Critical invariants under test:
 *   Proxy mode  – strict serialisation: at most 1 in-flight Image request at a time
 *   Proxy mode  – chaining: completing page N triggers page N+1 immediately
 *   Proxy mode  – currentPage change resets the chain from the new position
 *   Local mode  – concurrent fire-and-forget: up to 3 requests per page change
 *   Error path  – onerror must not stall the chain; next page is still attempted
 *
 * Test strategy:
 *   We replace window.Image with a controllable fake that captures every
 *   instance created.  Each fake exposes .triggerLoad() / .triggerError()
 *   so we can decide when a request "completes" and observe the side-effects.
 *
 *   Because useSequentialPrefetch uses React hooks we drive it with
 *   @testing-library/react renderHook + act.
 *
 * NOTE: install dependencies before running:
 *   pnpm add -D vitest @testing-library/react @testing-library/react-hooks jsdom
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
  /** Simulate a successful network response */
  triggerLoad: () => void
  /** Simulate a network error */
  triggerError: () => void
}

function makeFakeImageClass(): {
  FakeImage: new () => FakeImage
  instances: FakeImage[]
} {
  const instances: FakeImage[] = []

  class FakeImage {
    src = ''
    // hooks.ts assigns: el.onload = el.onerror = handler
    // so both properties start as null and the last assignment wins per element.
    onload: (() => void) | null = null
    onerror: (() => void) | null = null

    constructor() {
      instances.push(this)
    }

    triggerLoad() {
      this.onload?.()
    }

    triggerError() {
      // hooks.ts uses: el.onload = el.onerror = () => { ... }
      // Both point to the same handler after assignment.
      this.onerror?.()
    }
  }

  return { FakeImage, instances }
}

// ── Helpers ───────────────────────────────────────────────────────────

/** Build a ReaderImage array with sequential page numbers */
function makeImages(count: number, startPage = 1): ReaderImage[] {
  return Array.from({ length: count }, (_, i) => ({
    pageNum: startPage + i,
    url: `http://proxy/page/${startPage + i}`,
    isLocal: false,
    mediaType: 'image' as const,
  }))
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useSequentialPrefetch', () => {
  let instances: FakeImage[]

  beforeEach(() => {
    const { FakeImage, instances: inst } = makeFakeImageClass()
    instances = inst
    // Replace global Image with our fake for the duration of each test.
    vi.stubGlobal('Image', FakeImage)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  // ── Proxy mode ───────────────────────────────────────────────────

  describe('proxy mode', () => {
    it('should create exactly 1 in-flight Image request on initial render', () => {
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, /* currentPage */ 1, /* isProxyMode */ true))

      // Only page 2 should have been kicked off immediately.
      expect(instances).toHaveLength(1)
      expect(instances[0].src).toBe('http://proxy/page/2')
    })

    it('should NOT start a second request while the first is still in flight', () => {
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      // At this point page 2 is in flight; do not trigger its load yet.
      // The hook should not have created a second Image element.
      expect(instances).toHaveLength(1)
    })

    it('should chain to page N+1 immediately after page N loads', async () => {
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      // Page 2 in flight — complete it.
      expect(instances).toHaveLength(1)
      await act(async () => {
        instances[0].triggerLoad()
      })

      // Chain should have spawned the request for page 3.
      expect(instances).toHaveLength(2)
      expect(instances[1].src).toBe('http://proxy/page/3')
    })

    it('should chain all the way through remaining pages sequentially', async () => {
      // 5-page gallery, reading from page 1 → prefetch pages 2,3,4,5 in chain.
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      for (let expected = 2; expected <= 5; expected++) {
        expect(instances).toHaveLength(expected - 1)
        expect(instances[expected - 2].src).toBe(`http://proxy/page/${expected}`)

        await act(async () => {
          instances[expected - 2].triggerLoad()
        })
      }

      // After page 5 loads there is no page 6, so no further Image is created.
      expect(instances).toHaveLength(4)
    })

    it('should not skip already-prefetched pages when the chain runs', async () => {
      const images = makeImages(3)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      // Complete page 2.
      await act(async () => {
        instances[0].triggerLoad()
      })
      // Complete page 3.
      await act(async () => {
        instances[1].triggerLoad()
      })

      // No page 4 exists — chain terminates after exactly 2 requests.
      expect(instances).toHaveLength(2)
    })

    it('should continue the chain (not stall) when an image errors', async () => {
      const images = makeImages(4)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      // Page 2 errors.
      await act(async () => {
        instances[0].triggerError()
      })

      // Chain must have moved on to page 3 despite the error.
      expect(instances).toHaveLength(2)
      expect(instances[1].src).toBe('http://proxy/page/3')
    })

    it('should restart chain from new currentPage+1 when currentPage changes', async () => {
      const images = makeImages(10)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      // Page 2 is in flight; do NOT complete it — simulate user jumping ahead.
      expect(instances).toHaveLength(1)
      expect(instances[0].src).toBe('http://proxy/page/2')

      // User jumps to page 6.
      currentPage = 6
      await act(async () => {
        rerender()
      })

      // A new request for page 7 should be issued.
      // (inflightRef is false after the jump because the old in-flight image
      //  has not called its onload/onerror yet — the hook creates a new Image
      //  only when inflightRef is false.  This tests that the effect dependency
      //  on currentPage fires correctly.)
      //
      // Note: the first instance (page 2) is orphaned; its callback will call
      // prefetchPageRef.current(3) when it eventually fires, but prefetchedRef
      // would already contain page 3 or later by then, keeping the invariant.
      const pageSevenRequest = instances.find((img) => img.src === 'http://proxy/page/7')
      expect(pageSevenRequest).toBeDefined()
    })

    it('should not create a duplicate request for a page already in prefetchedRef', async () => {
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      // Complete page 2 → page 3 starts.
      await act(async () => {
        instances[0].triggerLoad()
      })
      const countAfterPage2 = instances.length

      // Simulate a stale callback firing again for page 2 (edge-case: two
      // quick page-jumps that share a prefetchedRef snapshot).
      // Page 2 is already in prefetchedRef so calling the chain manually
      // should be a no-op — we verify by checking instance count is stable.
      await act(async () => {
        // Trigger the orphaned page-2 image's onload a second time (simulate
        // a race where the same Image fires twice — browser behaviour).
        // Because prefetchedRef now contains page 2, the guard `if
        // (prefetchedRef.current.has(pageNum)) return` should block it.
        instances[0].triggerLoad()
      })

      expect(instances.length).toBe(countAfterPage2)
    })
  })

  // ── Local mode ───────────────────────────────────────────────────

  describe('local mode (concurrent)', () => {
    it('should fire up to 3 concurrent Image requests on initial render', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, /* currentPage */ 1, /* isProxyMode */ false))

      // Local mode: prefetch pages 2, 3, 4 concurrently in the same tick.
      expect(instances).toHaveLength(3)
      expect(instances.map((i) => i.src)).toEqual([
        'http://proxy/page/2',
        'http://proxy/page/3',
        'http://proxy/page/4',
      ])
    })

    it('should NOT wait for earlier requests to complete before firing all 3', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, false))

      // All 3 created synchronously — none have called onload yet.
      expect(instances).toHaveLength(3)
      // Completing the first should NOT trigger additional requests
      // (local mode has no chain; each page-change fires exactly 3).
      act(() => {
        instances[0].triggerLoad()
      })
      expect(instances).toHaveLength(3)
    })

    it('should fire 3 new requests when currentPage advances', async () => {
      const images = makeImages(10)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, false))

      expect(instances).toHaveLength(3) // pages 2,3,4

      currentPage = 4
      await act(async () => {
        rerender()
      })

      // New requests for pages 5, 6, 7 (pages 2/3/4 already prefetched — skipped).
      const srcs = instances.map((i) => i.src)
      expect(srcs).toContain('http://proxy/page/5')
      expect(srcs).toContain('http://proxy/page/6')
      expect(srcs).toContain('http://proxy/page/7')
    })

    it('should not exceed available pages even if 3 ahead would overflow', () => {
      // Only 2 pages ahead exist from currentPage 8 in a 9-page gallery.
      const images = makeImages(9)
      const currentPage = 8

      renderHook(() => useSequentialPrefetch(images, currentPage, false))

      // Should only create Image for page 9 — page 10 and 11 don't exist.
      expect(instances).toHaveLength(1)
      expect(instances[0].src).toBe('http://proxy/page/9')
    })

    it('should handle onerror without throwing and still mark page as prefetched', async () => {
      const images = makeImages(5)

      const { result } = renderHook(() => useSequentialPrefetch(images, 1, false))

      await act(async () => {
        instances[0].triggerError() // page 2 errors
      })

      // The set returned by the hook should include page 2 even on error,
      // because hooks.ts uses el.onload = el.onerror = same handler.
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
      const images = makeImages(5) // pages 1-5
      renderHook(() => useSequentialPrefetch(images, 5, true))
      // page 6 does not exist in images — no Image should be created.
      expect(instances).toHaveLength(0)
    })

    it('should return a Set containing the prefetched page numbers', async () => {
      const images = makeImages(3)

      const { result } = renderHook(() => useSequentialPrefetch(images, 1, true))

      expect(result.current).toBeInstanceOf(Set)
      expect(result.current.size).toBe(0) // nothing resolved yet

      await act(async () => {
        instances[0].triggerLoad()
      })

      expect(result.current.has(2)).toBe(true)
    })
  })
})
