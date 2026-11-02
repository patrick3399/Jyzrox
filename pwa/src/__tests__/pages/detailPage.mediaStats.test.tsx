/**
 * Library gallery detail page — media size and composition in the info block.
 *
 * Both sit with the secondary fields, so on phones they stay behind "More info".
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
vi.mock('@/components/RatingStars', () => ({ RatingStars: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => null }))

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'


const base = {
  id: 7,
  title: 'Gallery',
  source: 'local',
  source_id: '123',
  pages: 5,
  download_status: 'complete',
  tags_array: [],
  added_at: '2026-10-07T00:00:00Z',
}

describe('gallery detail page media stats', () => {
  beforeEach(() => {
    h.gallery = null
  })

  it('shows the total size and the gif/video counts, hidden on phones until More info', () => {
    h.gallery = {
      ...base,
      media_stats: { total_size: 1048576, image_count: 3, gif_count: 1, video_count: 1 },
    } as unknown as Gallery
    render(<GalleryDetailPage />)

    const size = screen.getByText('1 MiB')
    expect(size.parentElement).toHaveClass('hidden', 'md:block')
    const media = screen.getByText(/3 images/)
    expect(media).toHaveTextContent('3 images · 1 GIFs · 1 videos')
    expect(media.parentElement).toHaveClass('hidden', 'basis-full')
  })

  it('omits the composition row when every page is a plain image', () => {
    h.gallery = {
      ...base,
      media_stats: { total_size: 2048, image_count: 5, gif_count: 0, video_count: 0 },
    } as unknown as Gallery
    render(<GalleryDetailPage />)

    expect(screen.getByText('2 KiB')).toBeInTheDocument()
    expect(screen.queryByText(/images/)).not.toBeInTheDocument()
  })

  it('omits both rows when the gallery has no media stats yet', () => {
    h.gallery = { ...base } as unknown as Gallery
    render(<GalleryDetailPage />)

    expect(screen.queryByText(/MiB|KiB|GiB/)).not.toBeInTheDocument()
  })
})
