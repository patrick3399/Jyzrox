/**
 * The E-Hentai grid must hand the virtualizer the real row height.
 *
 * A grid tile is a 3:4 box whose text is overlaid, so its height is a pure
 * function of the column width. Guessing a constant and measuring rows as they
 * render looks fine while scrolling down from the top, but after a restore
 * every row above the restored position is still the guess: scrolling up then
 * corrects scrollTop by the guess error once per row, which reads as the list
 * stuttering backwards.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'

type GridProps = {
  measureRows?: boolean
  estimateHeight?:
    | number
    | ((context: { colCount: number; containerWidth: number; gap: number }) => number)
}
const gridProps = vi.fn<(props: GridProps) => void>()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams('tab=search'),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: GridProps) => {
    gridProps(props)
    return null
  },
}))
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(async () => ({
        galleries: [
          {
            gid: 1,
            token: 't1',
            title: 'Alpha',
            title_jpn: '',
            category: 'manga',
            thumb: '',
            uploader: 'u',
            posted_at: 0,
            pages: 1,
            rating: 0,
            tags: [],
            expunged: false,
          },
        ],
        total: 1,
        next_gid: null,
      })),
      getBrowseStatus: vi.fn(async () => ({ statuses: {} })),
    },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
  },
}))

import Page from '@/app/e-hentai/page'
import { estimateEhGridRowHeight } from '@/lib/ehLayout'

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'grid')
  gridProps.mockClear()
})

describe('e-hentai grid row height', () => {
  it('lays grid rows out at a fixed width-derived height instead of measuring a guessed one', async () => {
    render(<Page />)
    await waitFor(() => expect(gridProps).toHaveBeenCalled())

    const props = gridProps.mock.lastCall?.[0]
    expect(props?.measureRows).toBe(false)
    expect(props?.estimateHeight).toBe(estimateEhGridRowHeight)
  })

  it.each([
    // 1920px desktop, 8 columns: a tile measured 195.125 x 260.17 on the live page.
    { colCount: 8, containerWidth: 1617, gap: 8, tileHeight: 260.167 },
    // 390px phone, 3 columns.
    { colCount: 3, containerWidth: 358, gap: 8, tileHeight: 152 },
    // 768px tablet, 5 columns.
    { colCount: 5, containerWidth: 736, gap: 8, tileHeight: 187.733 },
  ])(
    'reserves the 3:4 tile height for $colCount columns in $containerWidth px without rounding below it',
    ({ colCount, containerWidth, gap, tileHeight }) => {
      const rowHeight = estimateEhGridRowHeight({ colCount, containerWidth, gap })

      // Fixed rows are placed rowHeight + gap apart: any shortfall makes the
      // next row overlap this one, and more than a pixel of slack is a visible gap.
      expect(rowHeight).toBeGreaterThanOrEqual(tileHeight)
      expect(rowHeight - tileHeight).toBeLessThan(1)
    },
  )
})
