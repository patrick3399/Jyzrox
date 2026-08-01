/**
 * VirtualGrid — Vitest test suite
 *
 * Regression coverage for the grid keyboard navigation bug where ArrowUp/Down
 * jumped by the parent's stale default colCount (4) instead of a full row.
 *
 * Root cause: VirtualGrid only emitted onColCountChange when the ResizeObserver
 * detected a change from its internally-initialised colCount. It never emitted
 * the initial value, so on wide desktop viewports — where the first observed
 * width maps to the same breakpoint as the initial window.innerWidth-derived
 * value — the parent's colCount stayed at its hard-coded default.
 *
 * These tests stub ResizeObserver as a no-op, so the ONLY way onColCountChange
 * can fire is the initial mount emit. That isolates the fix.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { VirtualGrid, getColumnCount, type ColumnConfig } from '@/components/VirtualGrid'

// Stub the window virtualizer — its scroll math is irrelevant to column-count
// notification and pulls in jsdom-unfriendly window measurement.
vi.mock('@tanstack/react-virtual', () => ({
  useWindowVirtualizer: () => ({
    getVirtualItems: () => [],
    getTotalSize: () => 0,
    measureElement: () => {},
    scrollToIndex: () => {},
    options: { scrollMargin: 0 },
  }),
}))

// No-op ResizeObserver: guarantees the only colCount notification comes from the
// initial mount emit, not from a resize callback.
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const LIBRARY_COLUMNS: ColumnConfig = { base: 4, sm: 5, md: 6, lg: 8, xl: 10, xxl: 12 }

function setWindowWidth(width: number): void {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true, writable: true })
}

describe('VirtualGrid onColCountChange', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', NoopResizeObserver)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('test_virtualGrid_emits_initial_colCount_on_mount_desktop_xxl', () => {
    setWindowWidth(1920) // xxl → 12 columns
    const onColCountChange = vi.fn<(count: number) => void>()

    render(
      <VirtualGrid
        items={[1, 2, 3, 4, 5]}
        columns={LIBRARY_COLUMNS}
        onColCountChange={onColCountChange}
        renderItem={(n) => <span>{n}</span>}
      />,
    )

    // Bug: parent never learns the real column count and keeps its default (4).
    // Fix: initial count is emitted on mount.
    expect(onColCountChange).toHaveBeenCalledWith(getColumnCount(1920, LIBRARY_COLUMNS))
    expect(getColumnCount(1920, LIBRARY_COLUMNS)).toBe(12)
  })

  it('test_virtualGrid_emits_initial_colCount_on_mount_mobile_base', () => {
    setWindowWidth(390) // base → 4 columns
    const onColCountChange = vi.fn<(count: number) => void>()

    render(
      <VirtualGrid
        items={[1, 2, 3]}
        columns={LIBRARY_COLUMNS}
        onColCountChange={onColCountChange}
        renderItem={(n) => <span>{n}</span>}
      />,
    )

    expect(onColCountChange).toHaveBeenCalledWith(4)
  })

  it('test_virtualGrid_disables_native_scroll_anchoring_during_upward_row_recycling', () => {
    const { container } = render(
      <VirtualGrid
        items={[1, 2, 3]}
        columns={{ base: 1 }}
        renderItem={(n) => <span>{n}</span>}
      />,
    )

    expect(container.firstElementChild).toHaveStyle({ overflowAnchor: 'none' })
  })
})
