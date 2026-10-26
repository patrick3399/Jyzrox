import { Suspense } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import UserProfilePage from '@/app/pixiv/user/[id]/page'
import { createBrowseSnapshotStore } from '@/lib/browse/snapshotStore'
import {
  PIXIV_BROWSE_SCHEMA_VERSION,
  PIXIV_BROWSE_SOURCE_ID,
  pixivIdentityKey,
  type PixivBrowseItem,
} from '@/lib/browse/pixiv'

/**
 * A follow toggled on the Pixiv artist page must reach the saved Pixiv lists
 * of this tab (the Following list): restored lists were never refreshed, so
 * the list the user went back to kept the old Follow / Unfollow button.
 */

const h = vi.hoisted(() => ({
  router: { back: vi.fn(), push: vi.fn(), replace: vi.fn() },
  search: '',
  api: {
    getUser: vi.fn(),
    getUserCollection: vi.fn(),
    getUserIllusts: vi.fn(),
    getUserBookmarks: vi.fn(),
    followUser: vi.fn(),
    unfollowUser: vi.fn(),
  },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => h.router,
  usePathname: () => '/pixiv/user/13419413',
  useSearchParams: () => new URLSearchParams(h.search),
}))
vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => undefined }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'alice' }, isLoading: false }),
}))
vi.mock('@/lib/api', () => ({
  api: {
    pixiv: {
      getUser: (...args: unknown[]) => h.api.getUser(...args),
      getUserCollection: (...args: unknown[]) => h.api.getUserCollection(...args),
      getUserIllusts: (...args: unknown[]) => h.api.getUserIllusts(...args),
      getUserBookmarks: (...args: unknown[]) => h.api.getUserBookmarks(...args),
      imageProxyUrl: (url: string) => url,
      followUser: (...args: unknown[]) => h.api.followUser(...args),
      unfollowUser: (...args: unknown[]) => h.api.unfollowUser(...args),
    },
    download: { enqueue: vi.fn() },
  },
}))

const USER_ID = 13419413
const USER_URL = `/pixiv/user/${USER_ID}`

function illust(id: number) {
  return {
    id,
    title: `Illust ${id}`,
    type: 'illust',
    image_urls: { square_medium: `/sq-${id}.jpg`, medium: '', large: '' },
    caption: '',
    user: { id: USER_ID, name: 'Artist', account: 'artist', profile_image: '/p.jpg' },
    tags: [],
    create_date: '2024-01-01T00:00:00+09:00',
    page_count: 1,
    width: 1,
    height: 1,
    sanity_level: 2,
    total_view: 1,
    total_bookmarks: 1,
    is_bookmarked: false,
  }
}

const USER_RESULT = {
  user: {
    id: USER_ID,
    name: 'Artist Name',
    account: 'artist',
    profile_image: '/avatar.jpg',
    comment: '',
    total_illusts: 3,
    total_manga: 0,
    total_novels: 0,
    is_followed: false,
  },
  recent_illusts: [] as ReturnType<typeof illust>[],
  next_offset: null,
}

function stubHistoryLength(length: number) {
  vi.spyOn(window.history, 'length', 'get').mockReturnValue(length)
}

function tree(cache: Map<string, unknown>, id: string) {
  return (
    <SWRConfig value={{ provider: () => cache as never, dedupingInterval: 0 }}>
      <Suspense>
        <UserProfilePage params={Promise.resolve({ id })} />
      </Suspense>
    </SWRConfig>
  )
}

async function renderPage(cache = new Map<string, unknown>(), id = String(USER_ID)) {
  let view!: ReturnType<typeof render>
  await act(async () => {
    view = render(tree(cache, id))
  })
  return { ...view, cache }
}

async function renderLoaded(cache = new Map<string, unknown>()) {
  const view = await renderPage(cache)
  await screen.findByText('Artist Name')
  return view
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  sessionStorage.setItem('browse_session_tab_id_v1', TAB_ID)
  h.search = ''
  window.history.replaceState({}, '', USER_URL)
  stubHistoryLength(3)
  h.api.getUser.mockResolvedValue(USER_RESULT)
  h.api.getUserCollection.mockResolvedValue({
    gallery_id: null,
    gallery_source_id: null,
    subscribed: false,
    subscription_id: null,
    job_id: null,
    job_status: null,
    work_count: 0,
    missing_count: 0,
  })
  h.api.getUserIllusts.mockResolvedValue({ illusts: [illust(1), illust(2)], next_offset: null })
  h.api.getUserBookmarks.mockResolvedValue({
    illusts: [illust(501), illust(502)],
    next_offset: null,
  })
  h.api.followUser.mockResolvedValue({ ok: true })
  h.api.unfollowUser.mockResolvedValue({ ok: true })
})

afterEach(() => {
  vi.restoreAllMocks()
})

const TAB_ID = 'tab-user'
const FOLLOWING = pixivIdentityKey({ surface: 'following', restrict: 'public' })

function store() {
  return createBrowseSnapshotStore<PixivBrowseItem, unknown>({
    storage: sessionStorage,
    scope: {
      userId: 'alice',
      tabId: TAB_ID,
      sourceId: PIXIV_BROWSE_SOURCE_ID,
      schemaVersion: PIXIV_BROWSE_SCHEMA_VERSION,
    },
  })
}

function artistItem(id: number, isFollowed: boolean): PixivBrowseItem {
  return {
    kind: 'user',
    preview: { user: { id, name: `Artist ${id}`, is_followed: isFollowed }, illusts: [] },
  }
}

function seedFollowing(items: PixivBrowseItem[]) {
  const saved = store().save(FOLLOWING, {
    pages: [items],
    cursor: null,
    hasMore: false,
    total: null,
    anchor: null,
    layout: null,
  })
  expect(saved).toBe(true)
}

function savedArtist(id: number) {
  return store()
    .load(FOLLOWING)
    ?.pages.flat()
    .find((item) => item.kind === 'user' && item.preview.user.id === id)
}

describe('Pixiv artist page — follow changes reach the saved Following list', () => {
  it('a follow here marks the artist followed in the saved Following list', async () => {
    seedFollowing([artistItem(USER_ID, false), artistItem(77, true)])
    await renderLoaded()

    fireEvent.click(await screen.findByRole('button', { name: /pixiv\.followOnPixiv/ }))

    await waitFor(() =>
      expect(savedArtist(USER_ID)).toMatchObject({ preview: { user: { is_followed: true } } }),
    )
    expect(h.api.followUser).toHaveBeenCalledWith(USER_ID)
    expect(savedArtist(77)).toMatchObject({ preview: { user: { is_followed: true } } })
  })

  it('an unfollow here resets the artist in the saved Following list', async () => {
    h.api.getUser.mockResolvedValue({
      ...USER_RESULT,
      user: { ...USER_RESULT.user, is_followed: true },
    })
    seedFollowing([artistItem(USER_ID, true)])
    await renderLoaded()

    fireEvent.click(await screen.findByRole('button', { name: /pixiv\.unfollowOnPixiv/ }))

    await waitFor(() =>
      expect(savedArtist(USER_ID)).toMatchObject({ preview: { user: { is_followed: false } } }),
    )
    expect(h.api.unfollowUser).toHaveBeenCalledWith(USER_ID)
  })

  it('a follow of an artist the saved Following list lacks discards that list', async () => {
    seedFollowing([artistItem(77, true)])
    await renderLoaded()

    fireEvent.click(await screen.findByRole('button', { name: /pixiv\.followOnPixiv/ }))

    await waitFor(() =>
      expect(store().restore(FOLLOWING)).toEqual({ kind: 'missing', replayable: true }),
    )
  })
})
