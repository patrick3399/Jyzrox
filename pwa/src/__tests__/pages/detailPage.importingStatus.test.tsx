/**
 * Library gallery detail page — the `importing` download status.
 *
 * A link gallery is registered before its pages are hashed and stays
 * `importing` until the first hash pass ends. The page must know the status
 * (not fall back to "Proxy Only") and show the in-progress banner.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  images: [] as unknown[],
  mutateGallery: vi.fn(),
  mutateImages: vi.fn(),
  lastEvent: null as unknown,
  connected: true,
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ source: 'local', sourceId: 'folder' }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
}))
vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('swr', () => ({
  default: () => ({ data: undefined, error: undefined, isLoading: false, mutate: vi.fn() }),
  mutate: vi.fn(),
}))
vi.mock('@/hooks/useGalleries', () => ({
  useLibraryGallery: () => ({
    data: h.gallery,
    isLoading: false,
    error: null,
    mutate: h.mutateGallery,
  }),
  useInfiniteGalleryImages: () => ({
    data: { images: h.images, favorited_image_ids: [] },
    isLoading: false,
    isLoadingMore: false,
    isReachingEnd: true,
    loadMore: vi.fn(),
    mutate: h.mutateImages,
  }),
  useUpdateGallery: () => ({ trigger: vi.fn(), isMutating: false }),
}))
vi.mock('@/hooks/useTagTranslations', () => ({ useTagTranslations: () => ({ data: undefined }) }))
vi.mock('@/hooks/useLinkGallerySync', () => ({ useLinkGallerySync: vi.fn() }))
vi.mock('@/hooks/useLongPress', () => ({ useLongPress: () => ({}) }))
vi.mock('@/lib/ws', () => ({
  useWsConnection: () => ({ connected: h.connected }),
  useWsJobs: () => ({ lastJobUpdate: null }),
  useWsEvents: () => ({ lastEvent: h.lastEvent }),
}))
vi.mock('@/lib/api', () => ({
  api: new Proxy(
    {},
    {
      get: () =>
        new Proxy(
          {},
          { get: () => vi.fn().mockResolvedValue({ tags: [], items: [] }) },
        ),
    },
  ),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/library/GalleryTagSection', () => ({ GalleryTagSection: () => null }))
vi.mock('@/components/AppImage', () => ({ AppImage: () => null }))
vi.mock('@/components/Reader/ImageContextMenu', () => ({ ImageContextMenu: () => null }))
vi.mock('@/components/SimilarImagesPanel', () => ({ SimilarImagesPanel: () => null }))
vi.mock('@/components/LazyDialogs', () => ({ LazySauceNaoModal: () => null }))
vi.mock('@/components/BackButton', () => ({ BackButton: () => null }))
vi.mock('@/components/RatingStars', () => ({ RatingStars: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => null }))

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

function makeGallery(over: Partial<Gallery>): Gallery {
  return {
    id: 7,
    title: 'Folder',
    source: 'local',
    source_id: 'folder',
    pages: 3,
    import_mode: 'link',
    download_status: 'importing',
    tags_array: [],
    added_at: '2026-10-07T00:00:00Z',
    ...over,
  } as Gallery
}

describe('gallery detail page importing status', () => {
  beforeEach(() => {
    h.gallery = makeGallery({})
    h.images = []
    h.lastEvent = null
    h.connected = true
    h.mutateGallery.mockClear()
    h.mutateImages.mockClear()
  })

  it('renders the Processing label for an importing gallery, not Proxy Only', () => {
    render(<GalleryDetailPage />)

    expect(screen.getByText('Processing')).toBeInTheDocument()
    expect(screen.queryByText('Proxy Only')).not.toBeInTheDocument()
  })

  it('shows the in-progress banner while the gallery is importing', () => {
    render(<GalleryDetailPage />)

    expect(
      screen.getByText('Download in progress — images appear as they are imported'),
    ).toBeInTheDocument()
  })

  it('polls for fresh data while importing and the WebSocket is down', () => {
    vi.useFakeTimers()
    try {
      h.connected = false
      render(<GalleryDetailPage />)
      expect(h.mutateImages).not.toHaveBeenCalled()

      vi.advanceTimersByTime(5000)

      expect(h.mutateGallery).toHaveBeenCalled()
      expect(h.mutateImages).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not poll for a complete gallery', () => {
    vi.useFakeTimers()
    try {
      h.connected = false
      h.gallery = makeGallery({ download_status: 'complete' })
      render(<GalleryDetailPage />)

      vi.advanceTimersByTime(10000)

      expect(h.mutateImages).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders the page count from the gallery row, falling back to the loaded images', () => {
    h.gallery = makeGallery({ pages: null as unknown as number })
    h.images = [{ id: 1, page_num: 1 }, { id: 2, page_num: 2 }]
    render(<GalleryDetailPage />)

    expect(screen.getByRole('heading', { name: /Images \(2 /i })).toBeInTheDocument()
  })
})
