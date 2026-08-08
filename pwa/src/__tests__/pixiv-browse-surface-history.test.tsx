import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PixivBrowseItem } from '@/lib/browse/pixiv'

type GridProps = {
  items: PixivBrowseItem[]
  renderItem: (item: PixivBrowseItem, index: number) => React.ReactNode
}

const runtime = vi.hoisted(() => ({
  events: [] as string[],
  search: '',
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (url: string) => {
      runtime.events.push(`push:${url}`)
    },
    replace: (url: string) => {
      runtime.events.push(`replace:${url}`)
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
    runtime.search = ''
    sessionStorage.clear()
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
})
