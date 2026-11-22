/**
 * Library gallery detail page — rating row.
 *
 * It used to open /library with an `artist_id:` search. The artist page
 * lists the same galleries and adds the read-everything entry point, so the
 * link goes there instead. (The separate "View all by this artist" button was
 * dropped as a duplicate of this link.)
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

const h = vi.hoisted(() => ({ gallery: null as unknown }))

vi.mock('next/navigation', () => ({
  useParams: () => ({ source: 'ehentai', sourceId: '123' }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
}))
vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: React.ReactNode
    href: string
    className?: string
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
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
vi.mock('@/components/RatingStars', () => ({
  RatingStars: ({ rating, readonly }: { rating: number; readonly?: boolean }) => (
    <div data-testid={readonly ? 'stars-readonly' : 'stars-editable'} data-rating={rating} />
  ),
}))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => null }))

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

function setGallery(extra: Record<string, unknown>) {
  h.gallery = {
    id: 7,
    title: 'Gallery',
    source: 'ehentai',
    source_id: '123',
    pages: 3,
    download_status: 'complete',
    tags_array: [],
    added_at: '2026-10-07T00:00:00Z',
    rating: 0,
    my_rating: null,
    ...extra,
  } as unknown as Gallery
}

describe('gallery detail page rating row', () => {
  it('shows no source rating when gallery.rating is 0', () => {
    setGallery({ rating: 0, my_rating: 3 })
    render(<GalleryDetailPage />)
    expect(screen.queryByTestId('source-rating')).toBeNull()
  })

  it('shows the source rating, labelled with the source name, when gallery.rating > 0', () => {
    setGallery({ rating: 4, my_rating: 3 })
    render(<GalleryDetailPage />)
    const el = screen.getByTestId('source-rating')
    expect(el).toHaveAttribute('aria-label', expect.stringContaining('E-Hentai'))
    expect(el.textContent).toContain('★4')
    expect(el).toHaveClass('ml-auto')
  })

  it('keeps the editable stars bound to my_rating, not the source rating', () => {
    setGallery({ rating: 4, my_rating: 2 })
    render(<GalleryDetailPage />)
    const stars = screen.getAllByTestId(/^stars-/)
    expect(stars).toHaveLength(1)
    expect(stars[0]).toHaveAttribute('data-rating', '2')
  })
})
