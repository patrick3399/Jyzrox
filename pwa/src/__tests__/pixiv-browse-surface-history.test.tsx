import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PixivBrowseItem } from '@/lib/browse/pixiv'

type GridProps = {
  items: PixivBrowseItem[]
  renderItem: (item: PixivBrowseItem, index: number) => React.ReactNode
}

const runtime = vi.hoisted(() => ({
  // Writes to the URL: window.history.pushState/replaceState (commitBrowseUrl).
  events: [] as string[],
  // Anything that reached the router instead.
  routerCalls: [] as string[],
  search: '',
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (url: string) => {
      runtime.routerCalls.push(`push:${url}`)
    },
    replace: (url: string) => {
      runtime.routerCalls.push(`replace:${url}`)
    },
  }),
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
      identityKey: 'ranking:daily',
      items: [],
      pages: [],
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
  VirtualGrid: (props: GridProps) => (
    <div data-testid="grid">{props.items.map((item, i) => props.renderItem(item, i))}</div>
  ),
}))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getCredentials: vi.fn() },
    pixiv: { imageProxyUrl: (url: string) => url, followUser: vi.fn(), unfollowUser: vi.fn() },
  },
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import PixivPage from '@/app/pixiv/page'

describe('root Pixiv — which identity changes are reachable by back', () => {
  beforeEach(() => {
    runtime.events = []
    runtime.routerCalls = []
    runtime.search = ''
    sessionStorage.clear()
    vi.spyOn(window.history, 'pushState').mockImplementation((state, _title, url) => {
      expect(state).toEqual({})
      runtime.events.push(`push:${url}`)
    })
    vi.spyOn(window.history, 'replaceState').mockImplementation((state, _title, url) => {
      expect(state).toEqual({})
      runtime.events.push(`replace:${url}`)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // Regression: every surface change went through router.replace, so
  // ranking -> feed -> bookmarks collapsed into one history entry. The browse
  // page has no back FAB, so on mobile the edge swipe is the only back
  // affordance and it left Pixiv entirely instead of stepping back a surface.
  // Matches the E-Hentai rule: a surface is a place, a filter is not.
  it('switching surface pushes so the previous surface stays reachable', () => {
    render(<PixivPage />)

    fireEvent.click(screen.getByRole('button', { name: 'pixiv.feedTab' }))

    expect(runtime.events).toEqual(['push:/pixiv?tab=feed'])
  })

  it('switching to bookmarks pushes', () => {
    render(<PixivPage />)

    fireEvent.click(screen.getByRole('button', { name: 'pixiv.bookmarks' }))

    expect(runtime.events).toEqual(['push:/pixiv?tab=bookmarks'])
  })

  it('changing a filter inside the same surface replaces', () => {
    render(<PixivPage />)

    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'weekly' } })

    expect(runtime.events).toEqual(['replace:/pixiv?tab=ranking&mode=weekly'])
  })

  it('toggling R18 inside the ranking surface replaces', () => {
    render(<PixivPage />)

    fireEvent.click(screen.getByRole('button', { name: 'browse.r18' }))

    expect(runtime.events.every((event) => event.startsWith('replace:'))).toBe(true)
    expect(runtime.events).toHaveLength(1)
  })

  it('changing bookmark visibility inside the bookmarks surface replaces', () => {
    runtime.search = 'tab=bookmarks&restrict=public'
    render(<PixivPage />)
    runtime.events = []

    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'private' } })

    expect(runtime.events).toEqual(['replace:/pixiv?tab=bookmarks&restrict=private'])
  })

  // Regression: identity commits went through router.push/replace, an RSC fetch
  // per change for a page that is already rendered, and on iOS standalone Safari
  // a document navigation with an empty query that landed on ranking (FE-T17).
  it('never routes a same-page identity change through the Next router', () => {
    render(<PixivPage />)

    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'weekly' } })
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.feedTab' }))
    fireEvent.change(screen.getByPlaceholderText('pixiv.searchPlaceholder'), {
      target: { value: 'miku' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.search' }))

    expect(runtime.events.length).toBeGreaterThan(0)
    expect(runtime.routerCalls).toEqual([])
  })

  it('still follows the URL when back/forward changes the surface', () => {
    const view = render(<PixivPage />)
    expect(screen.getByRole('button', { name: 'browse.ranking' })).toHaveAttribute(
      'aria-current',
      'page',
    )

    runtime.search = 'tab=feed'
    view.rerender(<PixivPage />)

    expect(screen.getByRole('button', { name: 'pixiv.feedTab' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(runtime.events).toEqual([])
  })
})
