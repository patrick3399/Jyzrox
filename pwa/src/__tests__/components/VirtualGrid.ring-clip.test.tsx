/**
 * VirtualGrid — focus-ring clipping regression
 *
 * Bug: each virtual row wrapper used `contain: 'layout style paint'`. The `paint`
 * value clips all painting to the row's box, so a grid cell's focus ring — drawn
 * OUTSIDE the cell border via box-shadow — had its top/bottom edge cut off at the
 * row boundary. Because adjacent (up/down) cells live in separate, paint-contained
 * absolutely-positioned rows, no z-index can lift the ring out of the clip. The
 * purple keyboard/hover outline therefore disappeared behind neighbouring rows.
 *
 * Fix: drop `paint` from the row containment (`'layout style'`). The row gap gives
 * the ~2-3px ring room to paint, and `layout` still provides the size isolation
 * virtualization needs.
 *
 * This test renders a single virtual row and asserts the wrapper is NOT
 * paint-contained — the exact condition that caused the clip.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { VirtualGrid, type ColumnConfig } from '@/components/VirtualGrid'

// No-op ResizeObserver: VirtualGrid installs one on mount; jsdom lacks it.
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Return one virtual row so a row wrapper actually renders (the default suite
// stubs an empty grid, which never mounts a row).
vi.mock('@tanstack/react-virtual', () => ({
  useWindowVirtualizer: () => ({
    getVirtualItems: () => [{ index: 0, key: 0, start: 0, size: 200 }],
    getTotalSize: () => 200,
    measureElement: () => {},
    scrollToIndex: () => {},
    options: { scrollMargin: 0 },
  }),
}))

const LIBRARY_COLUMNS: ColumnConfig = { base: 4, sm: 5, md: 6, lg: 8, xl: 10, xxl: 12 }

describe('VirtualGrid row containment (focus-ring clip)', () => {
  beforeEach(() => vi.stubGlobal('ResizeObserver', NoopResizeObserver))
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('test_virtualGrid_row_is_not_paint_contained_so_focus_ring_is_not_clipped', () => {
    const { container } = render(
      <VirtualGrid
        items={[1, 2, 3, 4, 5]}
        columns={LIBRARY_COLUMNS}
        gap={12}
        renderItem={(n) => <span>{n}</span>}
      />,
    )

    const row = container.querySelector<HTMLElement>('[data-index="0"]')
    expect(row).not.toBeNull()

    const contain = row!.style.contain
    // The bug: 'paint' clipped the ring at the row edge. It must be gone.
    expect(contain).not.toContain('paint')
    // But layout isolation (needed by virtualization) must stay.
    expect(contain).toContain('layout')
  })
})
