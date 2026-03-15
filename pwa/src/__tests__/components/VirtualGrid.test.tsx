/**
 * VirtualGrid.test.tsx
 *
 * Covers:
 *   getColumnCount — breakpoint resolution logic
 *   VirtualGrid    — empty items renders empty container
 *   VirtualGrid    — virtual rows are rendered using the virtualizer output
 *   VirtualGrid    — renderItem is called with the correct (item, index) arguments
 *   VirtualGrid    — isLoading + hasMore renders the default LoadingSpinner
 *   VirtualGrid    — custom loadingElement replaces the default spinner
 *   VirtualGrid    — hasMore=true without isLoading renders the load-more area (empty)
 *   VirtualGrid    — component renders without crashing with all optional props supplied
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'

// ── Mock @tanstack/react-virtual ──────────────────────────────────────

const mockGetVirtualItems = vi.fn()
const mockGetTotalSize = vi.fn()
const mockMeasureElement = vi.fn()
const mockScrollToIndex = vi.fn()

vi.mock('@tanstack/react-virtual', () => ({
  useWindowVirtualizer: vi.fn(() => ({
    getVirtualItems: mockGetVirtualItems,
    getTotalSize: mockGetTotalSize,
    measureElement: mockMeasureElement,
    scrollToIndex: mockScrollToIndex,
    options: { scrollMargin: 0 },
  })),
}))

// ── Mock ResizeObserver ───────────────────────────────────────────────

class MockResizeObserver {
  observe = vi.fn()
  disconnect = vi.fn()
  unobserve = vi.fn()
}
vi.stubGlobal('ResizeObserver', MockResizeObserver)

// ── Mock leaf components ──────────────────────────────────────────────

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}))

vi.mock('@/components/FastScroller', () => ({
  FastScroller: () => null,
}))

// ── Subject under test ────────────────────────────────────────────────

import { VirtualGrid, getColumnCount } from '@/components/VirtualGrid'
import type { ColumnConfig } from '@/components/VirtualGrid'

// ── Helpers ───────────────────────────────────────────────────────────

/** A columns config that exercises every breakpoint. */
const fullColumns: ColumnConfig = {
  base: 1,
  sm: 2,
  md: 3,
  lg: 4,
  xl: 5,
  xxl: 6,
}

/** Reset virtualizer mocks to sane defaults between tests. */
function setupVirtualizer(virtualItems: { key: number; index: number; start: number; size: number }[], totalSize = 0) {
  mockGetVirtualItems.mockReturnValue(virtualItems)
  mockGetTotalSize.mockReturnValue(totalSize)
}

beforeEach(() => {
  setupVirtualizer([], 0)
})

// ── getColumnCount unit tests ─────────────────────────────────────────

describe('getColumnCount', () => {
  it('returns base when width is below all breakpoints', () => {
    expect(getColumnCount(320, fullColumns)).toBe(1)
  })

  it('returns sm value at exactly 640 px', () => {
    expect(getColumnCount(640, fullColumns)).toBe(2)
  })

  it('returns md value at exactly 768 px', () => {
    expect(getColumnCount(768, fullColumns)).toBe(3)
  })

  it('returns lg value at exactly 1024 px', () => {
    expect(getColumnCount(1024, fullColumns)).toBe(4)
  })

  it('returns xl value at exactly 1280 px', () => {
    expect(getColumnCount(1280, fullColumns)).toBe(5)
  })

  it('returns xxl value at exactly 1536 px', () => {
    expect(getColumnCount(1536, fullColumns)).toBe(6)
  })

  it('falls back to base when optional breakpoints are not defined', () => {
    // Only base defined — all widths should return base.
    const minimal: ColumnConfig = { base: 3 }
    expect(getColumnCount(2000, minimal)).toBe(3)
  })

  it('uses the highest defined breakpoint when some are omitted', () => {
    // sm and lg only: 900 px falls between sm (640) and lg (1024), so sm wins.
    const partial: ColumnConfig = { base: 1, sm: 2, lg: 4 }
    expect(getColumnCount(900, partial)).toBe(2)
    expect(getColumnCount(1024, partial)).toBe(4)
  })
})

// ── VirtualGrid component tests ───────────────────────────────────────

describe('VirtualGrid', () => {
  it('renders an empty container when items array is empty', () => {
    const { container } = render(
      <VirtualGrid
        items={[]}
        columns={{ base: 3 }}
        renderItem={() => <div />}
      />
    )
    // The component returns early: a single <div> with no children.
    const root = container.firstElementChild!
    expect(root).toBeTruthy()
    expect(root.children).toHaveLength(0)
  })

  it('renders virtual rows returned by the virtualizer', () => {
    setupVirtualizer(
      [
        { key: 0, index: 0, start: 0, size: 280 },
        { key: 1, index: 1, start: 296, size: 280 },
      ],
      592,
    )

    const items = ['a', 'b', 'c', 'd', 'e', 'f']
    render(
      <VirtualGrid
        items={items}
        columns={{ base: 3 }}
        renderItem={(item) => <div data-testid={`item-${item}`}>{item}</div>}
      />
    )

    // Row 0 contains items a, b, c — all should be in the DOM.
    expect(screen.getByTestId('item-a')).toBeInTheDocument()
    expect(screen.getByTestId('item-b')).toBeInTheDocument()
    expect(screen.getByTestId('item-c')).toBeInTheDocument()
    // Row 1 contains items d, e, f.
    expect(screen.getByTestId('item-d')).toBeInTheDocument()
  })

  it('calls renderItem with the correct (item, globalIndex) arguments', () => {
    setupVirtualizer(
      [{ key: 0, index: 0, start: 0, size: 280 }],
      280,
    )

    const renderItem = vi.fn((item: string) => <div key={item}>{item}</div>)
    const items = ['x', 'y', 'z']

    render(
      <VirtualGrid
        items={items}
        columns={{ base: 3 }}
        renderItem={renderItem}
      />
    )

    // Row 0 spans globalIndex 0-2.
    expect(renderItem).toHaveBeenCalledWith('x', 0)
    expect(renderItem).toHaveBeenCalledWith('y', 1)
    expect(renderItem).toHaveBeenCalledWith('z', 2)
  })

  it('shows the default LoadingSpinner when isLoading=true and hasMore=true', () => {
    // Virtualizer returns no rows so the component still renders the loading area.
    setupVirtualizer([], 100)

    render(
      <VirtualGrid
        items={['a', 'b', 'c']}
        columns={{ base: 3 }}
        renderItem={() => <div />}
        isLoading={true}
        hasMore={true}
      />
    )

    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
  })

  it('renders a custom loadingElement instead of the default spinner', () => {
    setupVirtualizer([], 100)

    render(
      <VirtualGrid
        items={['a']}
        columns={{ base: 1 }}
        renderItem={() => <div />}
        isLoading={true}
        hasMore={true}
        loadingElement={<div data-testid="custom-loader">loading…</div>}
      />
    )

    expect(screen.getByTestId('custom-loader')).toBeInTheDocument()
    expect(screen.queryByTestId('loading-spinner')).not.toBeInTheDocument()
  })

  it('renders the load-more container when hasMore=true and isLoading=false', () => {
    setupVirtualizer([], 100)

    const { container } = render(
      <VirtualGrid
        items={['a']}
        columns={{ base: 1 }}
        renderItem={() => <div />}
        isLoading={false}
        hasMore={true}
      />
    )

    // The load-more wrapper div (flex justify-center py-4) is present but empty
    // because isLoading is false and loadingElement is not provided.
    const loadMore = container.querySelector('.flex.justify-center.py-4')
    expect(loadMore).toBeTruthy()
    expect(screen.queryByTestId('loading-spinner')).not.toBeInTheDocument()
  })

  it('does NOT render the load-more area when hasMore=false and isLoading=false', () => {
    setupVirtualizer([], 100)

    const { container } = render(
      <VirtualGrid
        items={['a']}
        columns={{ base: 1 }}
        renderItem={() => <div />}
        isLoading={false}
        hasMore={false}
      />
    )

    expect(container.querySelector('.flex.justify-center.py-4')).toBeNull()
  })

  it('renders without crashing when all optional props are supplied', () => {
    setupVirtualizer(
      [{ key: 0, index: 0, start: 0, size: 280 }],
      280,
    )

    const onLoadMore = vi.fn()
    const onColCountChange = vi.fn()
    const onRegisterElement = vi.fn()

    expect(() =>
      render(
        <VirtualGrid
          items={['a', 'b']}
          columns={fullColumns}
          gap={8}
          estimateHeight={320}
          overscan={2}
          className="test-grid"
          focusedIndex={0}
          isLoading={false}
          hasMore={false}
          onLoadMore={onLoadMore}
          onColCountChange={onColCountChange}
          onRegisterElement={onRegisterElement}
          renderItem={(item) => <div>{item}</div>}
        />
      )
    ).not.toThrow()
  })
})
