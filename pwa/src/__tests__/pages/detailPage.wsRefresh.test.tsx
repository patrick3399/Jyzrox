/**
 * Library gallery detail page — grid refresh on this gallery's WS events.
 *
 * SWR's global mutate(filter) skips useSWRInfinite keys, so the image grid
 * never refetches from WsInvalidationBridge. The page must call the infinite
 * hook's own mutate when gallery.* / import.* arrives for the open gallery.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { Gallery, WsMessage } from '@/lib/types'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  mutateGallery: vi.fn(),
  mutateImages: vi.fn(),
  lastEvent: null as WsMessage | null,
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
    data: { images: [], favorited_image_ids: [] },
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
  useWsConnection: () => ({ connected: true }),
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

function galleryEvent(eventType: string, galleryId: number): WsMessage {
  return {
    type: 'event',
    event: { event_type: eventType, resource_type: 'gallery', resource_id: galleryId, data: {} },
  } as WsMessage
}

describe('gallery detail page WS refresh', () => {
  beforeEach(() => {
    h.gallery = {
      id: 7,
      title: 'Folder',
      source: 'local',
      source_id: 'folder',
      pages: 3,
      import_mode: 'link',
      download_status: 'complete',
      tags_array: [],
      added_at: '2026-10-07T00:00:00Z',
    } as unknown as Gallery
    h.lastEvent = null
    h.mutateGallery.mockClear()
    h.mutateImages.mockClear()
  })

  it('refetches the image grid when gallery.updated arrives for this gallery', () => {
    const { rerender } = render(<GalleryDetailPage />)
    expect(h.mutateImages).not.toHaveBeenCalled()

    h.lastEvent = galleryEvent('gallery.updated', 7)
    rerender(<GalleryDetailPage />)

    expect(h.mutateImages).toHaveBeenCalledTimes(1)
  })

  it('does not refetch the grid for a gallery.updated event of another gallery', () => {
    const { rerender } = render(<GalleryDetailPage />)

    h.lastEvent = galleryEvent('gallery.updated', 99)
    rerender(<GalleryDetailPage />)

    expect(h.mutateImages).not.toHaveBeenCalled()
  })

  it('does not refetch the grid again when an unrelated re-render happens', () => {
    const { rerender } = render(<GalleryDetailPage />)
    h.lastEvent = galleryEvent('gallery.updated', 7)
    rerender(<GalleryDetailPage />)
    expect(h.mutateImages).toHaveBeenCalledTimes(1)

    rerender(<GalleryDetailPage />)

    expect(h.mutateImages).toHaveBeenCalledTimes(1)
  })
})
