/**
 * Gallery detail "repair" goes through POST /api/download/galleries/{id}/action
 * (not a plain re-download of the source URL), and a gallery with purged images
 * lets the user bring them back through include_excluded.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  excluded: [] as Array<{ blob_sha256: string; excluded_at: string | null }>,
  galleryAction: vi.fn(),
}))

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
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'u', role: 'member' } }),
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
      get: (_t, ns) =>
        ns === 'download'
          ? { galleryAction: h.galleryAction }
          : new Proxy(
              {},
              {
                get: (_u, fn) =>
                  fn === 'listExcluded'
                    ? () => Promise.resolve({ excluded: h.excluded })
                    : vi.fn().mockResolvedValue({ tags: [], items: [], images: [], excluded: [] }),
              },
            ),
    },
  ),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/library/GalleryTagSection', () => ({ GalleryTagSection: () => null }))
vi.mock('@/components/library/AddToCollectionMenu', () => ({ AddToCollectionMenu: () => null }))
vi.mock('@/components/AppImage', () => ({ AppImage: () => null }))
vi.mock('@/components/Reader/ImageContextMenu', () => ({ ImageContextMenu: () => null }))
vi.mock('@/components/SimilarImagesPanel', () => ({ SimilarImagesPanel: () => null }))
vi.mock('@/components/LazyDialogs', () => ({ LazySauceNaoModal: () => null }))
vi.mock('@/components/BackButton', () => ({ BackButton: () => null }))
vi.mock('@/components/RatingStars', () => ({ RatingStars: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => null }))

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

describe('gallery detail repair action', () => {
  beforeEach(() => {
    h.galleryAction.mockReset().mockResolvedValue({ kind: 'repair', job_id: 'job-9', status: 'queued' })
    h.excluded = []
    h.gallery = {
      id: 7,
      title: 'Gallery',
      source: 'ehentai',
      source_id: '123',
      source_url: 'https://e-hentai.org/g/123/abcdef0123/',
      pages: 3,
      download_status: 'partial',
      tags_array: [],
      added_at: '2026-10-07T00:00:00Z',
      category: 'Doujinshi',
    } as unknown as Gallery
  })

  it('repair action calls galleryAction with repair', async () => {
    render(<GalleryDetailPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Repair' }))

    await waitFor(() => expect(h.galleryAction).toHaveBeenCalledTimes(1))
    expect(h.galleryAction).toHaveBeenCalledWith(7, 'repair', false)
    // Nothing was purged, so no restore dialog stands between the click and the call.
    expect(screen.queryByTestId('repair-dialog')).not.toBeInTheDocument()
  })

  it('repair with purged images asks first and passes includeExcluded when ticked', async () => {
    h.excluded = [{ blob_sha256: 'a'.repeat(64), excluded_at: null }]
    render(<GalleryDetailPage />)

    // The excluded list loads after mount; the click only opens the dialog once it has.
    await waitFor(async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'Repair' }))
      expect(screen.getByTestId('repair-dialog')).toBeInTheDocument()
    })
    expect(h.galleryAction).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('repair-include-excluded'))
    fireEvent.click(screen.getByTestId('repair-confirm'))

    await waitFor(() => expect(h.galleryAction).toHaveBeenCalledWith(7, 'repair', true))
  })
})
