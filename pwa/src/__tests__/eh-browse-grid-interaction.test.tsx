/**
 * E-Hentai browse grid: keyboard focus and the anchor saved when leaving.
 *
 * 1. useGridKeyboard's `registerElement` was never wired into VirtualGrid's
 *    `onRegisterElement` on this page (Pixiv and Library do), so
 *    `findVisibleIndex` always returned null and the first arrow key after any
 *    scroll or restore focused index 0 and scrolled the window to the top.
 * 2. "Open random" picked a loaded gallery that may not be rendered. Anchoring
 *    on it stored offset 0 for an element that has no position, so back
 *    scrolled that gallery to the top of the viewport instead of returning the
 *    user to where they were.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const push = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  useSearchParams: () => new URLSearchParams(''),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))

// What the stubbed grid reports. Indices outside [0, renderedUntil) are
// "virtualized away" (never registered); indices below `visibleFrom` are
// rendered but above the viewport.
const gridConfig = { renderedUntil: Infinity, visibleFrom: 0, startIndex: 0 }
let lastFocusedIndex: number | null | undefined

vi.mock('@/components/VirtualGrid', async () => {
  const { useEffect } = await import('react')
  return {
    VirtualGrid: ({
      items,
      focusedIndex,
      onRegisterElement,
      onVisibleRangeChange,
      renderItem,
    }: {
      items: Array<{ gid: number }>
      focusedIndex?: number | null
      onRegisterElement?: (index: number, element: HTMLElement | null) => void
      onVisibleRangeChange?: (range: { startIndex: number; endIndex: number }) => void
      renderItem: (item: { gid: number }, index: number) => React.ReactNode
    }) => {
      lastFocusedIndex = focusedIndex
      useEffect(() => {
        onVisibleRangeChange?.({ startIndex: gridConfig.startIndex, endIndex: items.length - 1 })
      }, [items.length, onVisibleRangeChange])
      return (
        <div>
          {items.map((item, index) =>
            index >= gridConfig.renderedUntil ? null : (
              <div
                key={item.gid}
                ref={(element) => {
                  if (element) {
                    const above = index < gridConfig.visibleFrom
                    const top = above ? -400 + index * 10 : 120 + index * 10
                    element.getBoundingClientRect = () =>
                      ({ top, bottom: top + 100, left: 0, right: 100, width: 100, height: 100 }) as DOMRect
                  }
                  onRegisterElement?.(index, element)
                }}
              >
                {renderItem(item, index)}
              </div>
            ),
          )}
        </div>
      )
    },
  }
})
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(),
      getFavorites: vi.fn(),
      getPopular: vi.fn(),
      getToplist: vi.fn(),
      getBrowseStatus: vi.fn(async () => ({ statuses: {} })),
    },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
  },
}))

import Page from '@/app/e-hentai/page'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { snapshotStorageKey } from '@/lib/browse/snapshotStore'

const g = (gid: number) =>
  ({
    gid,
    token: `t${gid}`,
    title: `Gallery ${gid}`,
    title_jpn: '',
    category: 'manga',
    thumb: '',
    uploader: 'u',
    posted_at: 0,
    pages: 1,
    rating: 0,
    tags: [],
    expunged: false,
  }) as never

const ITEMS = [1, 2, 3, 4, 5, 6].map(g)

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'grid')
  vi.clearAllMocks()
  Object.assign(gridConfig, { renderedUntil: Infinity, visibleFrom: 0, startIndex: 0 })
  lastFocusedIndex = undefined
  ;(api.eh.getPopular as ReturnType<typeof vi.fn>).mockResolvedValue({
    galleries: ITEMS,
    total: ITEMS.length,
    page: 0,
  })
})

describe('E-Hentai grid keyboard navigation', () => {
  it('first ArrowRight after scrolling focuses the first visible cell, not index 0', async () => {
    // Cells 0-2 are above the viewport after a scroll/restore; 3-5 are on screen.
    gridConfig.visibleFrom = 3
    gridConfig.startIndex = 3
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Gallery 4')).toBeInTheDocument())

    fireEvent.keyDown(window, { key: 'ArrowRight' })

    await waitFor(() => expect(lastFocusedIndex).toBe(3))
  })

  it('first ArrowLeft after scrolling focuses the last visible cell', async () => {
    gridConfig.visibleFrom = 0
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Gallery 1')).toBeInTheDocument())

    fireEvent.keyDown(window, { key: 'ArrowLeft' })

    await waitFor(() => expect(lastFocusedIndex).toBe(5))
  })
})

describe('E-Hentai open-random anchor', () => {
  function readPopularAnchor() {
    const tabId = sessionStorage.getItem('browse_session_tab_id_v1')
    const scopedKey = snapshotStorageKey({
      userId: 'qa-user',
      tabId: tabId ?? '',
      sourceId: 'ehentai',
      schemaVersion: 1,
    })
    const store = JSON.parse(sessionStorage.getItem(scopedKey) ?? '{"entries":[]}') as {
      entries: Array<{
        identityKey: string
        snapshot: { anchor: { itemId: number | null; offset: number } | null }
      }>
    }
    return (
      store.entries.find((entry) => entry.identityKey.includes('"surface":"popular"'))?.snapshot
        .anchor ?? null
    )
  }

  it('does not anchor on a random pick that is not rendered; keeps the position the user was at', async () => {
    // Only cells 0-2 are in the DOM (virtualized) and the user is looking at
    // cell 1. The random pick is cell 5, which has no element to measure.
    gridConfig.renderedUntil = 3
    gridConfig.startIndex = 1
    vi.spyOn(Math, 'random').mockReturnValue(0.99)
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Gallery 1')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: t('browse.openRandom') }))

    expect(push).toHaveBeenCalledWith('/e-hentai/6/t6')
    const anchor = readPopularAnchor()
    // Anchoring on gallery 6 stored offset 0, so back scrolled it to the top of
    // the viewport. The anchor must stay on what was actually on screen.
    expect(anchor?.itemId).toBe(2)
    expect(anchor?.offset).toBe(130)
  })

  it('anchors on the random pick when it is rendered, using its measured offset', async () => {
    gridConfig.renderedUntil = 3
    gridConfig.startIndex = 1
    vi.spyOn(Math, 'random').mockReturnValue(0) // gallery 1, rendered
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Gallery 1')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: t('browse.openRandom') }))

    expect(push).toHaveBeenCalledWith('/e-hentai/1/t1')
    const anchor = readPopularAnchor()
    expect(anchor?.itemId).toBe(1)
    expect(anchor?.offset).toBe(120)
  })
})
