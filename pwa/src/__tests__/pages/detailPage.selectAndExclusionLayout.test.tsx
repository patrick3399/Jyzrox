/**
 * Gallery detail image section on a phone:
 * - select mode used to put five action buttons in a non-wrapping row next to
 *   the "Images" heading, pushing the page wider than the viewport. The
 *   actions now live in a fixed, wrapping bar outside the image card.
 * - the exclusion list used to render under the (infinite) thumbnail grid, so
 *   on a long gallery it was effectively unreachable. It now opens as a dialog.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  excluded: [] as Array<{ blob_sha256: string; excluded_at: string | null }>,
  images: [] as Array<Record<string, unknown>>,
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
    data: { images: h.images, favorited_image_ids: [] },
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
      get: () =>
        new Proxy(
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
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: ({
    items,
    renderItem,
  }: {
    items: unknown[]
    renderItem: (item: unknown, idx: number) => React.ReactNode
  }) => <div data-testid="thumb-grid">{items.map((item, i) => renderItem(item, i))}</div>,
}))

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

describe('gallery detail select bar and exclusion list', () => {
  beforeEach(() => {
    h.excluded = []
    h.images = Array.from({ length: 3 }, (_, i) => ({
      id: i + 1,
      page_num: i + 1,
      thumb_path: null,
    }))
    h.gallery = {
      id: 7,
      title: 'Gallery',
      source: 'ehentai',
      source_id: '123',
      pages: 3,
      download_status: 'complete',
      tags_array: [],
      added_at: '2026-10-07T00:00:00Z',
      category: 'Doujinshi',
    } as unknown as Gallery
  })

  it('select mode on a narrow screen puts its actions in a wrapping bar outside the image header', async () => {
    render(<GalleryDetailPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Select' }))

    const bar = screen.getByTestId('image-select-bar')
    expect(bar).toHaveClass('fixed', 'flex-wrap', 'left-0', 'right-0')
    for (const name of [/Exclude/, 'Select All', 'Invert', 'Cancel']) {
      expect(within(bar).getByRole('button', { name })).toBeInTheDocument()
    }
    // The heading row next to the grid no longer carries the action buttons.
    const heading = screen.getByRole('heading', { level: 2, name: /Images/ })
    expect(within(heading.parentElement as HTMLElement).queryAllByRole('button')).toHaveLength(0)
    expect(heading.closest('div.bg-vault-card')).not.toContainElement(bar)

    fireEvent.click(within(bar).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByTestId('image-select-bar')).not.toBeInTheDocument()
  })

  it('exclusion list with a long gallery opens as a dialog instead of below the thumbnail grid', async () => {
    h.excluded = [{ blob_sha256: 'a'.repeat(64), excluded_at: null }]
    render(<GalleryDetailPage />)

    fireEvent.click(await screen.findByRole('button', { name: /Exclusion List \(1\)/ }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByTestId('excluded-list')).toBeInTheDocument()
    expect(within(dialog).getByText(/^aaaaaaaaaaaaaaaa/)).toBeInTheDocument()
    // Nothing of the list is appended after the grid inside the image card.
    const card = screen.getByTestId('thumb-grid').closest('div.bg-vault-card') as HTMLElement
    expect(within(card).queryByTestId('excluded-list')).not.toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
