/**
 * VirtualGrid — onLoadMore gate regression coverage.
 *
 * The fired-at gate only reopens when items.length grows. A load cycle that
 * completes WITHOUT growing items (transient fetch error, append fully deduped
 * away upstream) used to leave the stamp equal to items.length, permanently
 * gating onLoadMore — the infinite scroll wedged with hasMore still true.
 *
 * The virtualizer is stubbed so every row is always "visible": the trigger
 * condition (last virtual row rendered) holds on each effect pass, which is
 * exactly the deep-scroll/overshoot state where the wedge bit in production.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { VirtualGrid } from '@/components/VirtualGrid'

vi.mock('@tanstack/react-virtual', () => ({
  useWindowVirtualizer: (opts: { count: number }) => ({
    getVirtualItems: () =>
      Array.from({ length: opts.count }, (_, i) => ({ index: i, key: i, start: i * 100 })),
    getTotalSize: () => opts.count * 100,
    measureElement: () => {},
    scrollToIndex: () => {},
    options: { scrollMargin: 0 },
  }),
}))

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function grid(items: number[], isLoading: boolean, onLoadMore: () => void) {
  return (
    <VirtualGrid
      items={items}
      columns={{ base: 2 }}
      hasMore
      isLoading={isLoading}
      onLoadMore={onLoadMore}
      renderItem={(n) => <span>{n}</span>}
    />
  )
}

describe('VirtualGrid onLoadMore gate', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', NoopResizeObserver)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('test_loadMore_refires_after_a_load_cycle_completes_without_items_growth', () => {
    const onLoadMore = vi.fn()
    const { rerender } = render(grid([1, 2], false, onLoadMore))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    // Load cycle runs… and completes with items unchanged (error / all-duplicate append)
    rerender(grid([1, 2], true, onLoadMore))
    expect(onLoadMore).toHaveBeenCalledTimes(1)
    rerender(grid([1, 2], false, onLoadMore))

    // Gate must reopen on the isLoading falling edge — before the fix the stamp
    // stayed at items.length and this never fired again.
    expect(onLoadMore).toHaveBeenCalledTimes(2)
  })

  it('test_loadMore_refires_only_after_growth_when_items_did_grow', () => {
    const onLoadMore = vi.fn()
    const { rerender } = render(grid([1, 2], false, onLoadMore))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    // Normal cycle: items grew — exactly one follow-up fire for the new length.
    rerender(grid([1, 2], true, onLoadMore))
    rerender(grid([1, 2, 3, 4], false, onLoadMore))
    expect(onLoadMore).toHaveBeenCalledTimes(2)

    // Same length again on a later render: still gated (no duplicate fire).
    rerender(grid([1, 2, 3, 4], false, onLoadMore))
    expect(onLoadMore).toHaveBeenCalledTimes(2)
  })
})
