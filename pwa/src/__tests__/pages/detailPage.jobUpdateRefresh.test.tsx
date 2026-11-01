/**
 * Library gallery detail page — refresh on job_update while downloading.
 *
 * Production log (2026-10-28 01:26, IG download at ~30 files/s): the page
 * refetched the gallery and image page 1 about 40 times a second until nginx's
 * api_zone answered 503 and the API answered 429. The job_update effect listed
 * the `gallery` object in its deps, so every refetch that changed the gallery
 * (pages grow during a download) re-ran the effect against the same, already
 * handled job_update and refetched again — a loop bounded only by request
 * latency. Refreshes must fire once per new job_update and be coalesced.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render } from '@testing-library/react'
import type { Gallery } from '@/lib/types'
import type { JobUpdateEvent } from '@/lib/ws'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  mutateGallery: vi.fn(),
  mutateImages: vi.fn(),
  lastJobUpdate: null as JobUpdateEvent | null,
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ source: 'instagram', sourceId: 'someone' }),
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
  useWsJobs: () => ({ lastJobUpdate: h.lastJobUpdate }),
  useWsEvents: () => ({ lastEvent: null }),
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

function jobUpdate(galleryId: number, downloaded: number): JobUpdateEvent {
  return { job_id: 'job-1', status: 'running', progress: { gallery_id: galleryId, downloaded } }
}

function downloadingGallery(pages: number): Gallery {
  return {
    id: 7,
    title: 'Someone',
    source: 'instagram',
    source_id: 'someone',
    pages,
    import_mode: 'download',
    download_status: 'downloading',
    tags_array: [],
    added_at: '2026-10-28T00:00:00Z',
  } as unknown as Gallery
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

describe('gallery detail page job_update refresh', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    h.gallery = downloadingGallery(10)
    h.lastJobUpdate = null
    h.mutateGallery.mockReset().mockResolvedValue(undefined)
    h.mutateImages.mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not refetch again when the refetched gallery object changes under the same job_update', async () => {
    const { rerender } = render(<GalleryDetailPage />)
    h.lastJobUpdate = jobUpdate(7, 5)
    rerender(<GalleryDetailPage />)
    await flush()
    expect(h.mutateGallery).toHaveBeenCalledTimes(1)
    expect(h.mutateImages).toHaveBeenCalledTimes(1)

    // The refetch resolves with more pages: a new gallery object, same event.
    for (let pages = 11; pages <= 15; pages++) {
      h.gallery = downloadingGallery(pages)
      rerender(<GalleryDetailPage />)
      await flush()
    }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })

    expect(h.mutateGallery).toHaveBeenCalledTimes(1)
    expect(h.mutateImages).toHaveBeenCalledTimes(1)
  })

  it('coalesces a burst of job_updates into one refresh plus one trailing refresh', async () => {
    const { rerender } = render(<GalleryDetailPage />)

    for (let n = 1; n <= 10; n++) {
      h.lastJobUpdate = jobUpdate(7, n * 5)
      rerender(<GalleryDetailPage />)
      await flush()
    }
    expect(h.mutateGallery).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })

    expect(h.mutateGallery).toHaveBeenCalledTimes(2)
    expect(h.mutateImages).toHaveBeenCalledTimes(2)
  })

  it('ignores job_updates for another gallery', async () => {
    const { rerender } = render(<GalleryDetailPage />)
    h.lastJobUpdate = jobUpdate(99, 5)
    rerender(<GalleryDetailPage />)
    await flush()

    expect(h.mutateGallery).not.toHaveBeenCalled()
    expect(h.mutateImages).not.toHaveBeenCalled()
  })
})
