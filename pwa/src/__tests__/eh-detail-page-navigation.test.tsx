/**
 * E-Hentai gallery detail page: keyboard shortcuts and non-content states.
 *
 * 1. The window keydown handler guarded only input/textarea, so Enter/Space on
 *    any focused control (back FAB, tag, favourite, Load more, Torrents link)
 *    also opened the reader at page 1, and Escape with the tag popover or the
 *    favourite picker open also left the page.
 * 2. The loading and error states had no fixed back control; the error state's
 *    inline button called a bare `router.back()` (no-op on a one-entry
 *    history), and an unparseable gid never fetched and spun forever.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

const router = vi.hoisted(() => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }))
const params = vi.hoisted(() => ({ gid: '123', token: 'abc' }))
const galleryState = vi.hoisted(() => ({
  data: undefined as unknown,
  error: undefined as Error | undefined,
}))

vi.mock('next/navigation', () => ({
  useParams: () => params,
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => `/e-hentai/${params.gid}/${params.token}`,
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/hooks/useGalleries', () => ({
  useEhGallery: () => galleryState,
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

import EhGalleryDetailPage from '@/app/e-hentai/[gid]/[token]/page'

const GALLERY = {
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
}
const READ_URL = '/e-hentai/read/123/abc?page=1'

function setHistoryLength(length: number) {
  Object.defineProperty(window.history, 'length', { configurable: true, value: length })
}

beforeEach(() => {
  vi.clearAllMocks()
  params.gid = '123'
  params.token = 'abc'
  galleryState.data = GALLERY
  galleryState.error = undefined
  setHistoryLength(3)
})

describe('detail page keyboard shortcuts', () => {
  it('plain Enter on the page opens the reader at page 1', () => {
    render(<EhGalleryDetailPage />)

    fireEvent.keyDown(document.body, { key: 'Enter' })

    expect(router.push).toHaveBeenCalledWith(READ_URL)
  })

  it('plain Escape goes back', () => {
    render(<EhGalleryDetailPage />)

    fireEvent.keyDown(document.body, { key: 'Escape' })

    expect(router.back).toHaveBeenCalledTimes(1)
    expect(router.push).not.toHaveBeenCalled()
  })

  it.each([
    ['the back FAB', () => screen.getByRole('button', { name: 'common.back' })],
    ['a tag', () => screen.getByRole('button', { name: 'glasses' })],
    ['the favourite button', () => screen.getByTitle('common.favorite')],
    ['the Torrents link', () => screen.getByText(/browse\.torrents/)],
  ])('Enter or Space on %s does not also open the reader', (_name, target) => {
    render(<EhGalleryDetailPage />)
    const element = target()

    fireEvent.keyDown(element, { key: 'Enter' })
    fireEvent.keyDown(element, { key: ' ' })

    expect(router.push).not.toHaveBeenCalled()
  })

  it('Escape with the tag popover open does not also leave the page', () => {
    render(<EhGalleryDetailPage />)
    fireEvent.click(screen.getByRole('button', { name: 'glasses' }))
    expect(screen.getByTestId('tag-popover')).toBeInTheDocument()

    fireEvent.keyDown(document.body, { key: 'Escape' })
    fireEvent.keyDown(document.body, { key: 'Enter' })

    expect(router.back).not.toHaveBeenCalled()
    expect(router.push).not.toHaveBeenCalled()
  })

  it('Escape with the favourite picker open closes it and does not leave the page', () => {
    render(<EhGalleryDetailPage />)
    fireEvent.click(screen.getByTitle('common.favorite'))
    expect(screen.getByPlaceholderText('browse.favoriteNote')).toBeInTheDocument()

    fireEvent.keyDown(document.body, { key: 'Escape' })

    expect(router.back).not.toHaveBeenCalled()
    expect(screen.queryByPlaceholderText('browse.favoriteNote')).toBeNull()
  })

  it('Escape typed into the favourite note field does not leave the page', () => {
    render(<EhGalleryDetailPage />)
    fireEvent.click(screen.getByTitle('common.favorite'))

    fireEvent.keyDown(screen.getByPlaceholderText('browse.favoriteNote'), { key: 'Escape' })

    expect(router.back).not.toHaveBeenCalled()
  })

  it('shortcuts work again once the favourite picker is closed', () => {
    render(<EhGalleryDetailPage />)
    fireEvent.click(screen.getByTitle('common.favorite'))
    fireEvent.keyDown(document.body, { key: 'Escape' })

    fireEvent.keyDown(document.body, { key: 'Escape' })

    expect(router.back).toHaveBeenCalledTimes(1)
  })
})

describe('detail page loading, error and invalid-id states', () => {
  it('error state: the back FAB pushes /e-hentai when history has nothing to go back to', () => {
    setHistoryLength(1)
    galleryState.data = undefined
    galleryState.error = new Error('boom')

    render(<EhGalleryDetailPage />)
    fireEvent.click(screen.getByRole('button', { name: 'common.back' }))

    expect(router.push).toHaveBeenCalledWith('/e-hentai')
  })

  it('error state: the inline back button resolves through smartBack, not a bare router.back()', () => {
    setHistoryLength(1)
    galleryState.data = undefined
    galleryState.error = new Error('boom')

    render(<EhGalleryDetailPage />)
    fireEvent.click(screen.getByRole('button', { name: 'reader.goBack' }))

    expect(router.back).not.toHaveBeenCalled()
    expect(router.push).toHaveBeenCalledWith('/e-hentai')
  })

  it('loading state carries a back control', () => {
    setHistoryLength(1)
    galleryState.data = undefined

    render(<EhGalleryDetailPage />)

    expect(screen.getByTestId('spinner')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'common.back' }))
    expect(router.push).toHaveBeenCalledWith('/e-hentai')
  })

  it('a non-numeric gid shows the invalid-id state with a back control instead of spinning forever', () => {
    setHistoryLength(1)
    params.gid = 'not-a-number'
    galleryState.data = undefined

    render(<EhGalleryDetailPage />)

    expect(screen.getByText('common.invalidId')).toBeInTheDocument()
    expect(screen.queryByTestId('spinner')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'common.back' }))
    expect(router.push).toHaveBeenCalledWith('/e-hentai')
  })

  it('a zero gid is invalid too', () => {
    params.gid = '0'
    galleryState.data = undefined

    render(<EhGalleryDetailPage />)

    expect(screen.getByText('common.invalidId')).toBeInTheDocument()
  })
})
