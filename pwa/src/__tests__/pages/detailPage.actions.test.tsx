/**
 * Library gallery detail page — header actions and role gating.
 *
 * Every write the header offers (favorite, rating, read later, category,
 * title, share, access, versions, merge, delete, update/repair, image
 * select) is `require_role("member")` on the backend, but the page used to
 * render all of them for viewers, who then got a 403 on tap. The low-use
 * actions also moved out of the header into a "More" sheet so the header
 * stays short on phones.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  role: undefined as string | undefined,
  ratingProps: [] as Array<{ readonly?: boolean }>,
  back: vi.fn(),
  push: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ source: 'ehentai', sourceId: '123' }),
  useRouter: () => ({ push: h.push, back: h.back, replace: vi.fn() }),
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
  useProfile: () => ({ data: h.role ? { username: 'u', role: h.role } : undefined }),
}))
vi.mock('@/hooks/useGalleries', () => ({
  useLibraryGallery: () => ({ data: h.gallery, isLoading: false, error: null, mutate: vi.fn() }),
  useInfiniteGalleryImages: () => ({
    data: {
      images: [{ id: 1, page_num: 1, thumb_path: '/t/1.webp', file_path: '/f/1.webp' }],
      favorited_image_ids: [],
    },
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
            get: () => vi.fn().mockResolvedValue({ tags: [], items: [], images: [], excluded: [] }),
          },
        ),
    },
  ),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/library/GalleryTagSection', () => ({ GalleryTagSection: () => null }))
vi.mock('@/components/library/AddToCollectionMenu', () => ({
  AddToCollectionMenu: () => <button type="button">Add to Collection</button>,
}))
vi.mock('@/components/AppImage', () => ({ AppImage: () => null }))
vi.mock('@/components/Reader/ImageContextMenu', () => ({ ImageContextMenu: () => null }))
vi.mock('@/components/SimilarImagesPanel', () => ({ SimilarImagesPanel: () => null }))
vi.mock('@/components/LazyDialogs', () => ({ LazySauceNaoModal: () => null }))
vi.mock('@/components/BackButton', () => ({ BackButton: () => null }))
vi.mock('@/components/RatingStars', () => ({
  RatingStars: (props: { readonly?: boolean }) => {
    h.ratingProps.push(props)
    return null
  },
}))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => null }))

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

const MEMBER_ONLY_SHEET_ITEMS = ['Share', 'Manage access', 'Versions', 'Delete Gallery']

function openMoreSheet() {
  fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
  return screen.getByRole('dialog', { name: 'More actions' })
}

describe('gallery detail page header actions', () => {
  beforeEach(() => {
    h.role = undefined
    h.ratingProps = []
    h.back.mockClear()
    h.push.mockClear()
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

  it('keeps low-use actions out of the header until the More sheet is opened for a member', () => {
    h.role = 'member'
    render(<GalleryDetailPage />)

    for (const label of MEMBER_ONLY_SHEET_ITEMS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument()
    }

    const sheet = openMoreSheet()
    for (const label of MEMBER_ONLY_SHEET_ITEMS) {
      expect(within(sheet).getByText(label)).toBeInTheDocument()
    }
    expect(within(sheet).getByText('View Source')).toBeInTheDocument()
    // The legacy gallery Merge action was removed in favour of the Explorer merge flow.
    expect(within(sheet).queryByText('Merge')).not.toBeInTheDocument()
    expect(screen.queryByText('Merge')).not.toBeInTheDocument()
  })

  it('shows member write controls in the header for a member', () => {
    h.role = 'member'
    render(<GalleryDetailPage />)

    expect(screen.getByRole('button', { name: '☆ Favorite' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Read Later' })).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Select' })).toBeInTheDocument()
    expect(h.ratingProps.at(-1)?.readonly).toBe(false)
  })

  it('hides member-only actions from the More sheet when the profile role is viewer', () => {
    h.role = 'viewer'
    render(<GalleryDetailPage />)

    const sheet = openMoreSheet()
    expect(within(sheet).getByText('View Source')).toBeInTheDocument()
    for (const label of MEMBER_ONLY_SHEET_ITEMS) {
      expect(within(sheet).queryByText(label)).not.toBeInTheDocument()
    }
  })

  it('hides header write controls and makes rating read-only when the profile role is viewer', () => {
    h.role = 'viewer'
    render(<GalleryDetailPage />)

    expect(screen.queryByRole('button', { name: '☆ Favorite' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Read Later' })).not.toBeInTheDocument()
    // Category is shown as text, not as an editable select.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.getByText('Doujinshi')).toBeInTheDocument()
    // Partial download would offer "Repair now", which enqueues a member-only download.
    expect(screen.queryByRole('button', { name: 'Repair' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Select' })).not.toBeInTheDocument()
    expect(h.ratingProps.at(-1)?.readonly).toBe(true)
    // Collections are per-user and open to viewers.
    expect(screen.getByRole('button', { name: 'Add to Collection' })).toBeInTheDocument()
  })

  it('treats a not-yet-loaded profile as read-only instead of flashing write actions', () => {
    h.role = undefined
    render(<GalleryDetailPage />)

    expect(screen.queryByRole('button', { name: '☆ Favorite' })).not.toBeInTheDocument()
    const sheet = openMoreSheet()
    expect(within(sheet).queryByText('Delete Gallery')).not.toBeInTheDocument()
  })

  it('closes the More sheet on Escape without also navigating back', () => {
    h.role = 'member'
    render(<GalleryDetailPage />)

    openMoreSheet()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'More actions' })).not.toBeInTheDocument()
    // The page binds Escape to "go back"; the sheet must swallow it.
    expect(h.back).not.toHaveBeenCalled()
    expect(h.push).not.toHaveBeenCalled()

    // With the sheet closed, Escape navigates away again.
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(h.back.mock.calls.length + h.push.mock.calls.length).toBe(1)
  })
})
