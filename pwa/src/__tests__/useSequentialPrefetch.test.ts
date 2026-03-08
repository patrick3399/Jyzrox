/**
 * useSequentialPrefetch — Vitest test suite
 *
 * Tests the prefetch hook used by the Reader component.
 * The hook has two modes:
 *   - Proxy mode: PROXY_PREFETCH_CONCURRENCY (2) concurrent slots with chaining
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
    it('should create 2 in-flight Image requests on initial render (concurrency=2)', () => {
      const images = makeImages(5)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      expect(instances).toHaveLength(2)
      expect(instances[0].src).toBe('http://proxy/page/2')
      expect(instances[1].src).toBe('http://proxy/page/3')
    })

    it('should NOT start more than 2 requests while both are in flight', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, true))

      expect(instances).toHaveLength(2)
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

      const { result } = renderHook(() => useSequentialPrefetch(images, 1, true))

      // Error page 2
      await act(async () => {
        instances[0].triggerError()
      })

      // The chain should have spawned at least one more request
      expect(instances.length).toBeGreaterThan(2)
    })

    it('should restart chain from new currentPage+1 when currentPage changes', async () => {
      const images = makeImages(10)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, true))

      expect(instances).toHaveLength(2)

      // User jumps to page 6
      currentPage = 6
      await act(async () => {
        rerender()
      })

      // Should have requests for pages 7 and 8
      const srcs = activeSrcs(instances)
      expect(srcs).toContain('http://proxy/page/7')
      expect(srcs).toContain('http://proxy/page/8')
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
    it('should fire up to 3 concurrent Image requests on initial render', () => {
      const images = makeImages(10)

      renderHook(() => useSequentialPrefetch(images, 1, false))

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

      expect(instances).toHaveLength(3)
      act(() => {
        instances[0].triggerLoad()
      })
      expect(instances).toHaveLength(3)
    })

    it('should fire 3 new requests when currentPage advances', async () => {
      const images = makeImages(10)
      let currentPage = 1

      const { rerender } = renderHook(() => useSequentialPrefetch(images, currentPage, false))

      expect(instances).toHaveLength(3)

      currentPage = 4
      await act(async () => {
        rerender()
      })

      const srcs = instances.map((i) => i.src)
      expect(srcs).toContain('http://proxy/page/5')
      expect(srcs).toContain('http://proxy/page/6')
      expect(srcs).toContain('http://proxy/page/7')
    })

    it('should not exceed available pages even if 3 ahead would overflow', () => {
      const images = makeImages(9)
      const currentPage = 8

      renderHook(() => useSequentialPrefetch(images, currentPage, false))

      expect(instances).toHaveLength(1)
      expect(instances[0].src).toBe('http://proxy/page/9')
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
})
