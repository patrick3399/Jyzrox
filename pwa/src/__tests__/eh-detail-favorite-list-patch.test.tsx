/**
 * A favourite change on the E-Hentai gallery page must reach the saved
 * Favorites lists of this tab. Restored lists were never refreshed, so after
 * un-favouriting a gallery the Favorites list the user went back to still
 * showed it, for the life of the browser tab.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const nav = vi.hoisted(() => ({ search: 'fav=1' }))
const h = vi.hoisted(() => ({
  gallery: {
    gid: 123,
    token: 'abc',
    title: 'Detail Gallery',
    title_jpn: '',
    category: 'Doujinshi',
    thumb: '',
    uploader: 'someone',
    posted_at: 1700000000,
    pages: 10,
    rating: 4.5,
    tags: ['female:glasses'],
    torrent_count: 1,
    expunged: false,
  },
  addFavorite: vi.fn(),
  removeFavorite: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ gid: '123', token: 'abc' }),
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
  usePathname: () => '/e-hentai/123/abc',
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))
vi.mock('@/hooks/useGalleries', () => ({
  useEhGallery: () => ({ data: h.gallery, error: undefined }),
  useEhGalleryPreviews: () => ({ data: undefined }),
  useEhGalleryComments: () => ({ data: undefined, isLoading: false }),
}))
vi.mock('@/hooks/useTagTranslations', () => ({
  useTagTranslations: () => ({ data: undefined }),
}))
vi.mock('swr', () => ({
  default: () => ({ data: undefined, mutate: vi.fn() }),
}))
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      thumbProxyUrl: (url: string) => url,
      getGalleryRelationships: vi.fn(),
      getFavoriteState: vi.fn(),
      getImagesPaginated: vi.fn(),
      addFavorite: (...args: unknown[]) => h.addFavorite(...args),
      removeFavorite: (...args: unknown[]) => h.removeFavorite(...args),
    },
    history: { record: vi.fn().mockResolvedValue({}) },
    download: { enqueue: vi.fn() },
  },
}))
vi.mock('dompurify', () => ({ default: { sanitize: (s: string) => s } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: h.toastError } }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/components/RatingStars', () => ({
  RatingStars: () => <span data-testid="rating" />,
}))
vi.mock('@/components/TagSearchPopover', () => ({
  TagSearchPopover: () => <div data-testid="tag-popover" />,
}))

import EhGalleryDetailPage from '@/app/e-hentai/[gid]/[token]/page'
import { ehIdentityKey } from '@/lib/browse/ehentai'
import { createBrowseSnapshotStore } from '@/lib/browse/snapshotStore'
import { initialFilters } from '@/lib/ehBrowseState'
import type { EhGallery } from '@/lib/types'

const TAB_ID = 'tab-eh-detail'
const favorites = (favCat: string) =>
  ehIdentityKey({ tab: 'favorites', query: '', filters: { ...initialFilters, favCat } })
const LATEST = ehIdentityKey({ tab: 'search', query: '', filters: initialFilters })

function store() {
  return createBrowseSnapshotStore<EhGallery, unknown>({
    storage: sessionStorage,
    scope: { userId: 'qa-user', tabId: TAB_ID, sourceId: 'ehentai', schemaVersion: 1 },
  })
}

function gallery(gid: number): EhGallery {
  return { ...h.gallery, gid, token: `t${gid}`, title: `G${gid}` }
}

function seed(identityKey: string, gids: number[], total: number) {
  const saved = store().save(identityKey, {
    pages: [gids.map(gallery)],
    cursor: null,
    hasMore: false,
    total,
    anchor: null,
    layout: null,
  })
  expect(saved).toBe(true)
}

function savedGids(identityKey: string) {
  return store()
    .load(identityKey)
    ?.pages.flat()
    .map((item) => item.gid)
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  sessionStorage.setItem('browse_session_tab_id_v1', TAB_ID)
  nav.search = 'fav=1'
  h.addFavorite.mockResolvedValue({})
  h.removeFavorite.mockResolvedValue({})
})

describe('E-Hentai gallery page — favourite changes reach the saved lists', () => {
  it('drops an un-favourited gallery from every saved Favorites list and its total', async () => {
    seed(favorites('all'), [123, 9], 2)
    seed(favorites('3'), [123], 1)
    seed(LATEST, [123, 9], 50)
    render(<EhGalleryDetailPage />)

    fireEvent.click(screen.getByTitle('common.favorite'))
    fireEvent.click(screen.getByText('browse.removeFromFavorites'))

    await waitFor(() => expect(savedGids(favorites('all'))).toEqual([9]))
    expect(h.removeFavorite).toHaveBeenCalledWith(123, 'abc')
    expect(store().load(favorites('all'))?.total).toBe(1)
    expect(savedGids(favorites('3'))).toEqual([])
    expect(store().load(favorites('3'))?.total).toBe(0)
    expect(savedGids(LATEST)).toEqual([123, 9])
  })

  it('moves a gallery to another category: out of the old list, kept in All, the new list discarded', async () => {
    seed(favorites('all'), [123, 9], 2)
    seed(favorites('3'), [123], 1)
    seed(favorites('2'), [9], 1)
    render(<EhGalleryDetailPage />)

    fireEvent.click(screen.getByTitle('common.favorite'))
    fireEvent.click(screen.getByText('Favorites 2'))

    await waitFor(() => expect(savedGids(favorites('3'))).toEqual([]))
    expect(h.addFavorite).toHaveBeenCalledWith(123, 'abc', 2, '')
    expect(savedGids(favorites('all'))).toEqual([123, 9])
    expect(store().restore(favorites('2'))).toEqual({ kind: 'missing', replayable: true })
  })

  it('leaves the saved lists alone when the favourite request fails', async () => {
    h.removeFavorite.mockRejectedValue(new Error('rejected'))
    seed(favorites('all'), [123, 9], 2)
    render(<EhGalleryDetailPage />)

    fireEvent.click(screen.getByTitle('common.favorite'))
    fireEvent.click(screen.getByText('browse.removeFromFavorites'))

    await waitFor(() => expect(h.toastError).toHaveBeenCalled())
    expect(savedGids(favorites('all'))).toEqual([123, 9])
  })
})
