/**
 * Library gallery detail page — where the artist links lead.
 *
 * They used to open /library with an `artist_id:` search. The artist page
 * lists the same galleries and adds the read-everything entry point, so both
 * links go there instead.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

const h = vi.hoisted(() => ({ gallery: null as unknown }))

vi.mock('next/navigation', () => ({
  useParams: () => ({ source: 'ehentai', sourceId: '123' }),
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
  useLibraryGallery: () => ({ data: h.gallery, isLoading: false, error: null, mutate: vi.fn() }),
  useInfiniteGalleryImages: () => ({
    data: { images: [], favorited_image_ids: [] },
    isLoading: false,
    isLoadingMore: false,
    isReachingEnd: true,
    loadMore: vi.fn(),
    mutate: vi.fn(),
  }),
  useUpdateGallery: () => ({ trigger: vi.fn(), isMutating: false }),
}))
vi.mock('@/hooks/useTagTranslations', () => ({ useTagTranslations: () => ({ data: undefined }) }))
vi.mock('@/hooks/useLinkGallerySync', () => ({ useLinkGallerySync: vi.fn() }))
vi.mock('@/hooks/useLongPress', () => ({ useLongPress: () => ({}) }))
vi.mock('@/lib/ws', () => ({
  useWsConnection: () => ({ connected: true }),
  useWsJobs: () => ({ lastJobUpdate: null }),
  useWsEvents: () => ({ lastEvent: null }),
}))
vi.mock('@/lib/api', () => ({
  api: new Proxy(
    {},
    {
      get: () => new Proxy({}, { get: () => vi.fn().mockResolvedValue({ tags: [], items: [] }) }),
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

const ARTIST_ID = 'ehentai:some artist/α'
const ARTIST_HREF = `/artists/${encodeURIComponent(ARTIST_ID)}`

describe('gallery detail page artist links', () => {
  beforeEach(() => {
    h.gallery = {
      id: 7,
      title: 'Gallery',
      source: 'ehentai',
      source_id: '123',
      pages: 3,
      download_status: 'complete',
      tags_array: [],
      added_at: '2026-10-07T00:00:00Z',
      artist_id: ARTIST_ID,
    } as unknown as Gallery
  })

  it('links the artist name to the artist page, not to a library search', () => {
    render(<GalleryDetailPage />)

    const link = screen.getByText('some artist/α').closest('a')
    expect(link).toHaveAttribute('href', ARTIST_HREF)
  })

  it('links the view-all-by-artist button to the artist page', () => {
    render(<GalleryDetailPage />)

    const link = screen.getByText('View all by this artist').closest('a')
    expect(link).toHaveAttribute('href', ARTIST_HREF)
  })
})
