/**
 * Pixiv grid surfaces must hand the virtualizer the real row height.
 *
 * Every Pixiv grid card is a square (or a strip of squares) followed by
 * single-line, truncated text, so its height is a function of the column width.
 * Guessing a constant (200 / 180) and measuring rows as they render leaves
 * every row above a restored position at the guess; scrolling up then corrects
 * scrollTop by the guess error once per row. On the following tab the guess was
 * off by 50-60px a row.
 *
 * List mode is different: its tag chips wrap, so those rows stay measured.
 */
import { fireEvent, render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PixivBrowseItem } from '@/lib/browse/pixiv'

type RowHeightContext = { colCount: number; containerWidth: number; gap: number }
type GridProps = {
  items: PixivBrowseItem[]
  renderItem: (item: PixivBrowseItem, index: number) => React.ReactNode
  measureRows?: boolean
  estimateHeight?: number | ((context: RowHeightContext) => number)
}

const runtime = vi.hoisted(() => ({
  search: '',
  gridProps: null as GridProps | null,
  items: [] as PixivBrowseItem[],
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(runtime.search),
}))
vi.mock('swr', () => ({
  default: () => ({ data: { pixiv: { configured: true } }, isLoading: false }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'alice' }, isLoading: false }),
}))
vi.mock('@/hooks/usePixivBrowseSession', () => ({
  usePixivBrowseSession: () => ({
    state: {
      identityKey: 'test',
      items: runtime.items,
      pages: [runtime.items],
      cursor: null,
      hasMore: false,
      total: null,
      generation: 1,
      status: 'idle',
      error: null,
      requestKind: null,
      failedRequest: null,
      terminal: null,
      meta: null,
    },
    checkpoint: vi.fn(),
    loadMore: vi.fn(),
    refresh: vi.fn(),
    retry: vi.fn(),
    replacePage: vi.fn(),
    restoreInstruction: null,
    acknowledgeRestore: vi.fn(),
    updateView: vi.fn(),
  }),
}))
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/hooks/useIllustActions', () => ({
  useIllustActions: () => ({
    downloading: false,
    bookmarked: false,
    bookmarking: false,
    handleDownload: vi.fn(),
    handleBookmark: vi.fn(),
  }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: GridProps) => {
    runtime.gridProps = props
    return (
      <div data-testid="grid">
        {props.items.map((item, index) => (
          <div key={`${item.kind}:${index}`}>{props.renderItem(item, index)}</div>
        ))}
      </div>
    )
  },
}))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getCredentials: vi.fn() },
    pixiv: {
      imageProxyUrl: (url: string) => url,
      followUser: vi.fn(),
      unfollowUser: vi.fn(),
    },
  },
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import PixivPage from '@/app/pixiv/page'
import {
  estimatePixivIllustRowHeight,
  estimatePixivRankingRowHeight,
  estimatePixivUserRowHeight,
} from '@/lib/pixivLayout'

const illustItem: PixivBrowseItem = {
  kind: 'illust',
  illust: {
    id: 11,
    title: 'Illust',
    image_urls: { square_medium: '/thumb.jpg' },
    user: { name: 'Artist' },
    page_count: 1,
    tags: [],
  },
}
const rankingItem: PixivBrowseItem = {
  kind: 'ranking',
  entry: { illust_id: 21, title: 'Ranked', user_name: 'Artist', url: '/rank.jpg', rank: 1 },
}
const userItem = {
  kind: 'user',
  preview: {
    user: { id: 31, name: 'Followed', profile_image: '/avatar.jpg' },
    illusts: [
      { id: 1, image_urls: { square_medium: '/a.jpg' } },
      { id: 2, image_urls: { square_medium: '/b.jpg' } },
      { id: 3, image_urls: { square_medium: '/c.jpg' } },
    ],
  },
} as unknown as PixivBrowseItem

function renderSurface(search: string, items: PixivBrowseItem[]) {
  runtime.search = search
  runtime.items = items
  const view = render(<PixivPage />)
  if (!runtime.gridProps) throw new Error('VirtualGrid was not rendered')
  return { view, props: runtime.gridProps }
}

beforeEach(() => {
  runtime.search = ''
  runtime.items = []
  runtime.gridProps = null
  localStorage.clear()
})

describe('pixiv grid row height wiring', () => {
  it.each([
    { name: 'feed', search: 'tab=feed', items: [illustItem], estimator: estimatePixivIllustRowHeight },
    {
      name: 'ranking',
      search: 'tab=ranking',
      items: [rankingItem],
      estimator: estimatePixivRankingRowHeight,
    },
    {
      name: 'following',
      search: 'tab=following',
      items: [userItem],
      estimator: estimatePixivUserRowHeight,
    },
  ])(
    'lays $name grid rows out at a fixed width-derived height instead of measuring a guessed one',
    ({ search, items, estimator }) => {
      const { props } = renderSurface(search, items)

      expect(props.measureRows).toBe(false)
      expect(props.estimateHeight).toBe(estimator)
    },
  )

  it('keeps measuring list-mode rows because their tag chips wrap to a variable height', () => {
    localStorage.setItem('pixiv_view_mode', 'list')

    const { props } = renderSurface('tab=feed', [illustItem])

    expect(props.measureRows).not.toBe(false)
  })

  it('keeps the box of a following-card thumbnail that fails to load so the row height still holds', () => {
    const { view } = renderSurface('tab=following', [userItem])
    const thumbnail = view.container.querySelector<HTMLImageElement>('img[src="/a.jpg"]')
    if (!thumbnail) throw new Error('thumbnail not rendered')

    fireEvent.error(thumbnail)

    expect(thumbnail.style.display).not.toBe('none')
    expect(thumbnail.style.visibility).toBe('hidden')
  })

  it('keeps the box of a following-card avatar that fails to load so the row height still holds', () => {
    const { view } = renderSurface('tab=following', [userItem])
    const avatar = view.container.querySelector<HTMLImageElement>('img[src="/avatar.jpg"]')
    if (!avatar) throw new Error('avatar not rendered')

    fireEvent.error(avatar)

    expect(avatar.style.display).not.toBe('none')
    expect(avatar.style.visibility).toBe('hidden')
  })
})

describe('pixiv grid row height', () => {
  // Card heights below were measured on the live page in a 1160px-wide grid.
  it.each([
    {
      name: 'an illust card (square + 59px of text) in 6 columns',
      estimate: estimatePixivIllustRowHeight,
      layout: { colCount: 6, containerWidth: 1160, gap: 12 },
      cardHeight: 242.336,
    },
    {
      name: 'a ranking card (square + 42px of text) in 7 columns',
      estimate: estimatePixivRankingRowHeight,
      layout: { colCount: 7, containerWidth: 1160, gap: 8 },
      cardHeight: 200.859,
    },
    {
      // The no-works placeholder is the tallest variant of this card.
      name: 'a following card without works (3:1 strip + 46px footer) in 5 columns',
      estimate: estimatePixivUserRowHeight,
      layout: { colCount: 5, containerWidth: 1160, gap: 12 },
      cardHeight: 119.461,
    },
  ])('reserves the height of $name without rounding below it', ({ estimate, layout, cardHeight }) => {
    const rowHeight = estimate(layout)

    // Fixed rows are placed rowHeight + gap apart: any shortfall makes the next
    // row overlap this one, and more than a pixel of slack is a visible gap.
    expect(rowHeight).toBeGreaterThanOrEqual(cardHeight)
    expect(rowHeight - cardHeight).toBeLessThan(1)
  })

  it('scales the reserved text height with the root font size so larger text never overlaps the next row', () => {
    const layout = { colCount: 6, containerWidth: 1160, gap: 12 }
    const atDefault = estimatePixivIllustRowHeight(layout)
    document.documentElement.style.fontSize = '20px'
    try {
      // 2.75rem of the 59px text block follows the root font size: 44px -> 55px.
      expect(estimatePixivIllustRowHeight(layout)).toBe(atDefault + 11)
    } finally {
      document.documentElement.style.fontSize = ''
    }
  })
})
