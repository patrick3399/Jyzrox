import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Bookmark and follow toggles on the root Pixiv list, against the real browse
 * session and sessionStorage. Each toggle used to call refresh() at the full
 * loaded depth (one Pixiv request per loaded page), and a toggle that settled
 * after the user opened the work refreshed an unmounted list, so the saved
 * snapshot — and the list on back — kept the old state.
 */

const h = vi.hoisted(() => ({
  search: 'tab=feed',
  push: vi.fn(),
  feed: vi.fn(),
  following: vi.fn(),
  addBookmark: vi.fn(),
  deleteBookmark: vi.fn(),
  followUser: vi.fn(),
  unfollowUser: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: h.push, replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(h.search),
}))
vi.mock('swr', () => ({
  default: () => ({ data: { pixiv: { configured: true } }, isLoading: false }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'alice' }, isLoading: false }),
}))
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: {
    items: Array<{ kind: string }>
    renderItem: (item: { kind: string }, index: number) => React.ReactNode
  }) => (
    <div data-testid="grid">
      {props.items.map((item, index) => (
        <div key={index}>{props.renderItem(item, index)}</div>
      ))}
    </div>
  ),
}))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getCredentials: vi.fn() },
    download: { enqueue: vi.fn() },
    pixiv: {
      getFollowingFeed: (...args: unknown[]) => h.feed(...args),
      getFollowing: (...args: unknown[]) => h.following(...args),
      addBookmark: (...args: unknown[]) => h.addBookmark(...args),
      deleteBookmark: (...args: unknown[]) => h.deleteBookmark(...args),
      followUser: (...args: unknown[]) => h.followUser(...args),
      unfollowUser: (...args: unknown[]) => h.unfollowUser(...args),
      imageProxyUrl: (url: string) => url,
    },
  },
}))

import PixivPage from '@/app/pixiv/page'
import { createBrowseSnapshotStore } from '@/lib/browse/snapshotStore'
import { pixivIdentityKey, type PixivBrowseItem } from '@/lib/browse/pixiv'

function illust(id: number) {
  return {
    id,
    title: `Illust ${id}`,
    image_urls: { square_medium: `/sq-${id}.jpg` },
    user: { id: 9, name: 'Artist' },
    tags: [],
    page_count: 1,
    total_view: 1,
    total_bookmarks: 1,
    is_bookmarked: false,
  }
}

function followed(id: number) {
  return {
    user: { id, name: `Artist ${id}`, account: `a${id}`, profile_image: '', is_followed: true },
    illusts: [],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  localStorage.clear()
  h.search = 'tab=feed'
  h.feed.mockResolvedValue({ illusts: [illust(1), illust(2)], next_offset: 30 })
  h.following.mockResolvedValue({ user_previews: [followed(5), followed(6)], next_offset: null })
  h.addBookmark.mockResolvedValue({ ok: true })
  h.deleteBookmark.mockResolvedValue({ ok: true })
  h.followUser.mockResolvedValue({ ok: true })
  h.unfollowUser.mockResolvedValue({ ok: true })
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('root Pixiv list — bookmark and follow toggles', () => {
  it('a star tap marks the work in place and on return, without refetching the feed', async () => {
    const first = render(<PixivPage />)
    await screen.findByText('Illust 1')

    fireEvent.click(screen.getAllByText('☆')[0])

    await waitFor(() => expect(h.addBookmark).toHaveBeenCalledWith(1))
    await screen.findByText('★')
    first.unmount()

    render(<PixivPage />)
    await screen.findByText('Illust 1')
    expect(screen.getAllByText('★')).toHaveLength(1)
    expect(screen.getAllByText('☆')).toHaveLength(1)
    expect(h.feed).toHaveBeenCalledTimes(1)
  })

  it('a bookmark that settles after the user opened the work still reaches the list they return to', async () => {
    let settle!: (value: unknown) => void
    h.addBookmark.mockReturnValue(new Promise((resolve) => (settle = resolve)))
    const first = render(<PixivPage />)
    await screen.findByText('Illust 1')

    fireEvent.click(screen.getAllByText('☆')[0])
    fireEvent.click(screen.getByText('Illust 1'))
    expect(h.push).toHaveBeenCalledWith('/pixiv/illust/1')
    first.unmount()
    await act(async () => settle({ ok: true }))

    render(<PixivPage />)
    await screen.findByText('Illust 1')
    expect(screen.getAllByText('★')).toHaveLength(1)
    expect(h.feed).toHaveBeenCalledTimes(1)
  })

  it('an unfollow on the Following list keeps the artist with a Follow button, also on return, without refetching', async () => {
    h.search = 'tab=following'
    const first = render(<PixivPage />)
    await screen.findByText('Artist 5')

    fireEvent.click(screen.getAllByText('pixiv.unfollow')[0])

    await waitFor(() => expect(h.unfollowUser).toHaveBeenCalledWith(5))
    await screen.findByText('pixiv.follow')
    first.unmount()

    render(<PixivPage />)
    await screen.findByText('Artist 5')
    expect(screen.getAllByText('pixiv.follow')).toHaveLength(1)
    expect(screen.getAllByText('pixiv.unfollow')).toHaveLength(1)
    expect(h.following).toHaveBeenCalledTimes(1)
  })

  it('the Refresh button reloads only the first page of a deep restored list', async () => {
    sessionStorage.setItem('browse_session_tab_id_v1', 'tab-p')
    createBrowseSnapshotStore<PixivBrowseItem, unknown>({
      storage: sessionStorage,
      scope: { userId: 'alice', tabId: 'tab-p', sourceId: 'pixiv', schemaVersion: 1 },
    }).save(pixivIdentityKey({ surface: 'feed' }), {
      pages: [
        [{ kind: 'illust', illust: illust(1) }],
        [{ kind: 'illust', illust: illust(2) }],
        [{ kind: 'illust', illust: illust(3) }],
      ],
      cursor: { kind: 'offset', value: 90 },
      hasMore: true,
      total: null,
      anchor: null,
      layout: null,
    })
    h.feed.mockResolvedValue({ illusts: [illust(10)], next_offset: 30 })
    render(<PixivPage />)
    await screen.findByText('Illust 3')
    expect(h.feed).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'common.refresh' }))

    await screen.findByText('Illust 10')
    expect(h.feed).toHaveBeenCalledTimes(1)
    expect(h.feed).toHaveBeenCalledWith(0, expect.anything())
    expect(screen.queryByText('Illust 3')).toBeNull()
  })
})
