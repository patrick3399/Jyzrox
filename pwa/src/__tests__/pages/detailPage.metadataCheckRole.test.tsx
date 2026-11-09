/**
 * The detail page auto-runs POST .../check-update on EH/Pixiv galleries. That
 * endpoint applies source metadata (a write: member role + gallery write access
 * on the backend), so a viewer's page visit must not call it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  role: 'member' as string,
  checkUpdate: vi.fn(),
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
  // check every visit (0 days) so only the role decides whether the check runs
  default: (key: unknown) => ({
    data: key === 'settings/features' ? { gallery_update_check_days: 0 } : undefined,
    error: undefined,
    isLoading: false,
    mutate: vi.fn(),
  }),
  mutate: vi.fn(),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'u', role: h.role } }),
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
        new Proxy(
          {},
          {
            get: (_u, fn) =>
              ns === 'library' && fn === 'checkUpdate'
                ? h.checkUpdate
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

describe('gallery detail metadata auto-check by role', () => {
  beforeEach(() => {
    h.checkUpdate.mockReset().mockResolvedValue({ status: 'unchanged' })
    h.gallery = {
      id: 7,
      title: 'Gallery',
      source: 'ehentai',
      source_id: '123',
      source_url: 'https://e-hentai.org/g/123/abcdef0123/',
      pages: 3,
      download_status: 'complete',
      tags_array: [],
      added_at: '2026-10-07T00:00:00Z',
      metadata_updated_at: null,
      category: 'Doujinshi',
    } as unknown as Gallery
  })

  it('member visit runs the metadata check', async () => {
    h.role = 'member'
    render(<GalleryDetailPage />)

    await waitFor(() => expect(h.checkUpdate).toHaveBeenCalledWith('ehentai', '123'))
  })

  it('viewer visit does not call check-update', async () => {
    h.role = 'viewer'
    const { findAllByText } = render(<GalleryDetailPage />)

    // Let mount effects settle before asserting the absence of the call.
    await findAllByText('Gallery')
    await new Promise((r) => setTimeout(r, 20))
    expect(h.checkUpdate).not.toHaveBeenCalled()
  })
})
