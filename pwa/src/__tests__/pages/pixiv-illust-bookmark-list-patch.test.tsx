import { Suspense } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * A bookmark toggled on the Pixiv artwork page must reach the saved Pixiv
 * lists of this tab: restored lists were never refreshed, so the list the
 * user went back to kept the old star.
 */

const h = vi.hoisted(() => ({
  api: {
    getIllust: vi.fn(),
    getBookmarkStatus: vi.fn(),
    addBookmark: vi.fn(),
    deleteBookmark: vi.fn(),
  },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/pixiv/illust/118801677',
}))
vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => undefined }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/components/TagSearchPopover', () => ({ TagSearchPopover: () => null }))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'alice' }, isLoading: false }),
}))
vi.mock('@/lib/api', () => ({
  api: {
    pixiv: {
      getIllust: (...args: unknown[]) => h.api.getIllust(...args),
      getBookmarkStatus: (...args: unknown[]) => h.api.getBookmarkStatus(...args),
      addBookmark: (...args: unknown[]) => h.api.addBookmark(...args),
      deleteBookmark: (...args: unknown[]) => h.api.deleteBookmark(...args),
      imageProxyUrl: (url: string) => url,
    },
    download: { enqueue: vi.fn() },
  },
}))

import IllustDetailPage from '@/app/pixiv/illust/[id]/page'
import { createBrowseSnapshotStore } from '@/lib/browse/snapshotStore'
import {
  PIXIV_BROWSE_SCHEMA_VERSION,
  PIXIV_BROWSE_SOURCE_ID,
  pixivIdentityKey,
  type PixivBrowseItem,
} from '@/lib/browse/pixiv'

const ILLUST_ID = 118801677
const TAB_ID = 'tab-illust'
const FEED = pixivIdentityKey({ surface: 'feed' })

const ILLUST = {
  id: ILLUST_ID,
  title: 'Artwork title',
  type: 'illust',
  image_urls: { square_medium: '/sq.jpg', medium: '/m.jpg', large: '/l.jpg' },
  caption: '',
  user: { id: 13419413, name: 'Artist', account: 'artist', profile_image: '/p.jpg' },
  tags: [{ name: 'blue', translated_name: null }],
  create_date: '2024-01-01T00:00:00+09:00',
  page_count: 1,
  width: 1,
  height: 1,
  sanity_level: 2,
  total_view: 10,
  total_bookmarks: 5,
  is_bookmarked: false,
}

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

function seedFeed(isBookmarked: boolean) {
  const saved = store().save(FEED, {
    pages: [
      [
        {
          kind: 'illust',
          illust: {
            id: ILLUST_ID,
            title: 'Artwork title',
            is_bookmarked: isBookmarked,
            total_bookmarks: 5,
          },
        },
        {
          kind: 'illust',
          illust: { id: 2, title: 'Other', is_bookmarked: false, total_bookmarks: 1 },
        },
      ],
    ],
    cursor: null,
    hasMore: false,
    total: null,
    anchor: null,
    layout: null,
  })
  expect(saved).toBe(true)
}

function savedWork(id: number) {
  return store()
    .load(FEED)
    ?.pages.flat()
    .find((item) => item.kind === 'illust' && item.illust.id === id)
}

async function renderLoaded() {
  await act(async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <Suspense>
          <IllustDetailPage params={Promise.resolve({ id: String(ILLUST_ID) })} />
        </Suspense>
      </SWRConfig>,
    )
  })
  await screen.findByText('Artwork title')
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  sessionStorage.setItem('browse_session_tab_id_v1', TAB_ID)
  h.api.getIllust.mockResolvedValue(ILLUST)
  h.api.getBookmarkStatus.mockResolvedValue({ is_bookmarked: false })
  h.api.addBookmark.mockResolvedValue({ ok: true })
  h.api.deleteBookmark.mockResolvedValue({ ok: true })
})

describe('Pixiv artwork page — bookmark changes reach the saved lists', () => {
  it('a bookmark added here stars the work in the saved list the user goes back to', async () => {
    seedFeed(false)
    await renderLoaded()

    fireEvent.click(await screen.findByRole('button', { name: 'pixiv.addBookmark' }))

    await waitFor(() =>
      expect(savedWork(ILLUST_ID)).toMatchObject({
        illust: { is_bookmarked: true, total_bookmarks: 6 },
      }),
    )
    expect(h.api.addBookmark).toHaveBeenCalledWith(ILLUST_ID)
    expect(savedWork(2)).toMatchObject({ illust: { is_bookmarked: false, total_bookmarks: 1 } })
  })

  it('a bookmark removed here clears the star in the saved list', async () => {
    seedFeed(true)
    h.api.getBookmarkStatus.mockResolvedValue({ is_bookmarked: true })
    await renderLoaded()

    fireEvent.click(await screen.findByRole('button', { name: 'pixiv.removeBookmark' }))

    await waitFor(() =>
      expect(savedWork(ILLUST_ID)).toMatchObject({
        illust: { is_bookmarked: false, total_bookmarks: 4 },
      }),
    )
    expect(h.api.deleteBookmark).toHaveBeenCalledWith(ILLUST_ID)
  })

  it('leaves the saved list alone when the bookmark request fails', async () => {
    seedFeed(false)
    h.api.addBookmark.mockRejectedValue(new Error('rate limited'))
    await renderLoaded()

    fireEvent.click(await screen.findByRole('button', { name: 'pixiv.addBookmark' }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'pixiv.addBookmark' })).not.toBeDisabled(),
    )
    expect(h.api.addBookmark).toHaveBeenCalledTimes(1)
    expect(savedWork(ILLUST_ID)).toMatchObject({
      illust: { is_bookmarked: false, total_bookmarks: 5 },
    })
  })
})
