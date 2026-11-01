/**
 * Regression (audit EH-3): the gallery detail page forgot everything it had
 * loaded when the reader was opened.
 *
 * Load more -> scroll to thumbnail 120 -> tap it -> exit the reader: the page
 * remounted with only the first preview batch (extra previews, hasMore and
 * infinite-scroll mode were component state), so the document was much shorter
 * and the browser's native scroll restoration landed on the wrong content.
 * The paginated previews and the UI around them now survive a remount, and the
 * scroll position captured at the moment of leaving is re-applied once the
 * restored content has rendered.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

const router = vi.hoisted(() => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }))
const params = vi.hoisted(() => ({ gid: '123', token: 'abc' }))
const getImagesPaginated = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useParams: () => params,
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => `/e-hentai/${params.gid}/${params.token}`,
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/hooks/useGalleries', () => ({
  useEhGallery: () => ({ data: GALLERY, error: undefined }),
  useEhGalleryPreviews: () => ({
    data: { previews: { '1': 'first-1.jpg', '2': 'first-2.jpg' } },
  }),
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
      getImagesPaginated: (...args: unknown[]) => getImagesPaginated(...args),
      addFavorite: vi.fn(),
      removeFavorite: vi.fn(),
    },
    history: { record: vi.fn().mockResolvedValue({}) },
    download: { enqueue: vi.fn() },
  },
}))
vi.mock('dompurify', () => ({ default: { sanitize: (s: string) => s } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/components/RatingStars', () => ({
  RatingStars: () => <span data-testid="rating" />,
}))
vi.mock('@/components/TagSearchPopover', () => ({
  TagSearchPopover: () => <div data-testid="tag-popover" />,
}))
vi.mock('@/components/BackButton', () => ({
  BackButton: () => <button data-testid="back">Back</button>,
}))

import EhGalleryDetailPage from '@/app/e-hentai/[gid]/[token]/page'
import { clearEhDetailViews } from '@/lib/ehDetailView'

const GALLERY = {
  gid: 123,
  token: 'abc',
  title: 'Detail Gallery',
  title_jpn: '',
  category: 'Doujinshi',
  thumb: '',
  uploader: 'someone',
  posted_at: 1700000000,
  pages: 200,
  rating: 4.5,
  tags: [],
  expunged: false,
}

function setScrollY(value: number) {
  Object.defineProperty(window, 'scrollY', { value, configurable: true, writable: true })
}

class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

let scrollTo: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
  clearEhDetailViews()
  params.gid = '123'
  params.token = 'abc'
  setScrollY(0)
  scrollTo = vi.fn()
  vi.stubGlobal('scrollTo', scrollTo)
  vi.stubGlobal('ResizeObserver', NoopObserver)
  vi.stubGlobal('IntersectionObserver', NoopObserver)
  getImagesPaginated.mockResolvedValue({
    previews: { '3': 'more-3.jpg', '4': 'more-4.jpg', '120': 'more-120.jpg' },
    has_more: true,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function loadMoreAndOpenThumb() {
  const first = render(<EhGalleryDetailPage />)
  fireEvent.click(screen.getByRole('button', { name: 'browse.loadMorePreviews' }))
  await waitFor(() => expect(screen.getByAltText('Page 120')).toBeInTheDocument())
  expect(getImagesPaginated).toHaveBeenCalledTimes(1)

  // Deep in the page, as real scrolling would leave it.
  setScrollY(4200)
  fireEvent.click(screen.getByAltText('Page 120'))
  expect(router.push).toHaveBeenCalledWith('/e-hentai/read/123/abc?page=120')

  // Next scrolls to the top before the old page's cleanups run.
  setScrollY(0)
  first.unmount()
}

describe('gallery detail page across a reader round trip', () => {
  it('remounting shows the previews loaded by Load more without requesting them again', async () => {
    await loadMoreAndOpenThumb()

    render(<EhGalleryDetailPage />)

    // Synchronously on the first render: no refetch, no first-batch-only page.
    expect(screen.getByAltText('Page 4')).toBeInTheDocument()
    expect(screen.getByAltText('Page 120')).toBeInTheDocument()
    expect(getImagesPaginated).toHaveBeenCalledTimes(1)
    // Infinite-scroll mode is restored too, so the manual button stays gone.
    expect(screen.queryByRole('button', { name: 'browse.loadMorePreviews' })).toBeNull()
  })

  it('re-applies the scroll position captured when the user left, not the router reset', async () => {
    await loadMoreAndOpenThumb()
    scrollTo.mockClear()

    render(<EhGalleryDetailPage />)

    expect(scrollTo).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledWith(0, 4200)
  })

  it('applies a banked scroll once: a later visit does not jump again', async () => {
    await loadMoreAndOpenThumb()
    const second = render(<EhGalleryDetailPage />)
    second.unmount()
    scrollTo.mockClear()

    render(<EhGalleryDetailPage />)

    expect(scrollTo).not.toHaveBeenCalled()
    // The loaded previews still survive; only the one-shot scroll is spent.
    expect(screen.getByAltText('Page 120')).toBeInTheDocument()
  })

  it('does not scroll when the user left by some route that banked no position', async () => {
    const first = render(<EhGalleryDetailPage />)
    fireEvent.click(screen.getByRole('button', { name: 'browse.loadMorePreviews' }))
    await waitFor(() => expect(screen.getByAltText('Page 120')).toBeInTheDocument())
    first.unmount()
    scrollTo.mockClear()

    render(<EhGalleryDetailPage />)

    expect(screen.getByAltText('Page 120')).toBeInTheDocument()
    expect(scrollTo).not.toHaveBeenCalled()
  })

  it('does not leak one gallery’s loaded previews into another', async () => {
    await loadMoreAndOpenThumb()
    cleanup()
    params.token = 'other'

    render(<EhGalleryDetailPage />)

    expect(screen.queryByAltText('Page 120')).toBeNull()
    expect(scrollTo).not.toHaveBeenCalled()
  })
})
