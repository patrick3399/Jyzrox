/**
 * Library gallery detail page: keyboard shortcuts and the error state's exit.
 *
 * 1. The window keydown handler guarded only input/textarea/select, so Enter or
 *    Space on any focused control (header buttons, a page thumbnail) also opened
 *    the reader at page 1, and Escape/ArrowUp with the tag popover, the
 *    add-to-collection sheet, the image menu or an image panel open also left
 *    the page. Its back path was a bare history check, so a nav-tab restore of
 *    this page history-backed out of the section instead of climbing to the
 *    library list.
 * 2. The error state's only exit was an inline `router.back()`, a no-op on a
 *    one-entry history (share link, new tab, PWA relaunch).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { Gallery } from '@/lib/types'
import { markTabRestore, rememberLocation } from '@/lib/navMemory'

const h = vi.hoisted(() => ({
  gallery: null as unknown,
  error: null as Error | null,
  back: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ source: 'ehentai', sourceId: '123' }),
  useRouter: () => ({ push: h.push, back: h.back, replace: h.replace }),
  usePathname: () => '/library/ehentai/123',
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
  useLibraryGallery: () => ({
    data: h.gallery,
    isLoading: false,
    error: h.error,
    mutate: vi.fn(),
  }),
  useInfiniteGalleryImages: () => ({
    data: {
      images: [
        { id: 1, page_num: 1, thumb_path: '/t/1.webp', file_path: '/f/1.webp' },
        { id: 2, page_num: 2, thumb_path: '/t/2.webp', file_path: '/f/2.webp' },
      ],
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
// Right-click opens the image menu straight away (the real hook waits for a hold).
vi.mock('@/hooks/useLongPress', () => ({
  useLongPress: ({ onLongPress }: { onLongPress: (e: React.MouseEvent) => void }) => ({
    onTouchStart: () => {},
    onTouchMove: () => {},
    onTouchEnd: () => {},
    onContextMenu: (e: React.MouseEvent) => onLongPress(e),
  }),
}))
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
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))
vi.mock('@/components/TagSearchPopover', () => ({
  TagSearchPopover: () => <div data-testid="tag-popover" />,
}))
vi.mock('@/components/AppImage', () => ({ AppImage: () => null }))
vi.mock('@/components/Reader/ImageContextMenu', () => ({
  ImageContextMenu: ({
    onFindSimilar,
    onFindSource,
  }: {
    onFindSimilar: () => void
    onFindSource: () => void
  }) => (
    <div data-testid="image-menu">
      <button type="button" onClick={onFindSimilar}>
        find similar
      </button>
      <button type="button" onClick={onFindSource}>
        find source
      </button>
    </div>
  ),
}))
vi.mock('@/components/SimilarImagesPanel', () => ({
  SimilarImagesPanel: () => <div data-testid="similar-panel" />,
}))
vi.mock('@/components/LazyDialogs', () => ({
  LazySauceNaoModal: () => <div data-testid="saucenao-modal" />,
}))
vi.mock('@/components/RatingStars', () => ({ RatingStars: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: <T,>({
    items,
    renderItem,
  }: {
    items: T[]
    renderItem: (item: T, index: number) => React.ReactNode
  }) => <>{items.map((item, index) => renderItem(item, index))}</>,
}))

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

const READER_URL = '/reader/ehentai/123'

function setHistoryLength(length: number) {
  Object.defineProperty(window.history, 'length', { configurable: true, value: length })
}

function navigated() {
  return h.back.mock.calls.length + h.push.mock.calls.length + h.replace.mock.calls.length
}

function pageThumbnail(pageNum: number) {
  const tiles = screen
    .getAllByRole('button')
    .filter((el) => el.tagName === 'DIV' && el.getAttribute('tabindex') === '0')
  return tiles[pageNum - 1]
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  setHistoryLength(3)
  h.error = null
  h.gallery = {
    id: 7,
    title: 'Gallery',
    source: 'ehentai',
    source_id: '123',
    source_url: 'https://e-hentai.org/g/123/abcdef0123/',
    pages: 2,
    download_status: 'complete',
    tags_array: ['female:glasses'],
    added_at: '2026-10-07T00:00:00Z',
    category: 'Doujinshi',
  } as unknown as Gallery
})

afterEach(() => {
  delete (window.history as unknown as { length?: number }).length
  window.history.replaceState({}, '', '/')
})

describe('library detail page keyboard shortcuts', () => {
  it('plain Enter on the page opens the reader', () => {
    render(<GalleryDetailPage />)

    fireEvent.keyDown(document.body, { key: 'Enter' })

    expect(h.push).toHaveBeenCalledWith(READER_URL)
  })

  it.each([
    ['the Read Later button', () => screen.getByRole('button', { name: 'Read Later' })],
    ['the More actions button', () => screen.getByRole('button', { name: 'More actions' })],
    ['the Add to Collection button', () => screen.getByRole('button', { name: 'Add to Collection' })],
    ['a tag', () => screen.getByRole('button', { name: 'glasses' })],
  ])('Enter or Space on %s does not also open the reader', (_name, target) => {
    render(<GalleryDetailPage />)
    const element = target()

    fireEvent.keyDown(element, { key: 'Enter' })
    fireEvent.keyDown(element, { key: ' ' })

    expect(h.push).not.toHaveBeenCalled()
  })

  it('Enter on a focused page thumbnail opens that page instead of page 1', () => {
    render(<GalleryDetailPage />)

    fireEvent.keyDown(pageThumbnail(2), { key: 'Enter' })

    expect(h.push).toHaveBeenCalledTimes(1)
    expect(h.push).toHaveBeenCalledWith(`${READER_URL}?page=2`)
  })

  it('Escape on a focused button still goes back', () => {
    render(<GalleryDetailPage />)

    fireEvent.keyDown(screen.getByRole('button', { name: 'Read Later' }), { key: 'Escape' })

    expect(h.back).toHaveBeenCalledTimes(1)
  })

  it('Escape, ArrowUp and Enter with the tag popover open leave the page alone', () => {
    render(<GalleryDetailPage />)
    fireEvent.click(screen.getByRole('button', { name: 'glasses' }))
    expect(screen.getByTestId('tag-popover')).toBeInTheDocument()

    fireEvent.keyDown(document.body, { key: 'Escape' })
    fireEvent.keyDown(document.body, { key: 'ArrowUp' })
    fireEvent.keyDown(document.body, { key: 'Enter' })

    expect(navigated()).toBe(0)
  })

  it('Escape with the add-to-collection sheet open closes it without leaving the page', () => {
    render(<GalleryDetailPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Add to Collection' }))
    expect(screen.getByRole('dialog', { name: 'Add to Collection' })).toBeInTheDocument()

    fireEvent.keyDown(document.body, { key: 'ArrowUp' })
    fireEvent.keyDown(document.body, { key: 'Escape' })

    expect(screen.queryByRole('dialog', { name: 'Add to Collection' })).toBeNull()
    expect(navigated()).toBe(0)

    // With the sheet closed, Escape leaves the page again.
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(h.back).toHaveBeenCalledTimes(1)
  })

  it('Escape and Enter with the image context menu open leave the page alone', () => {
    render(<GalleryDetailPage />)
    fireEvent.contextMenu(pageThumbnail(1))
    expect(screen.getByTestId('image-menu')).toBeInTheDocument()

    fireEvent.keyDown(document.body, { key: 'Escape' })
    fireEvent.keyDown(document.body, { key: 'Enter' })

    expect(navigated()).toBe(0)
  })

  it.each([
    ['similar images panel', 'find similar', 'similar-panel'],
    ['SauceNAO dialog', 'find source', 'saucenao-modal'],
  ])('Escape and Enter with the %s open leave the page alone', (_name, opener, testId) => {
    render(<GalleryDetailPage />)
    fireEvent.contextMenu(pageThumbnail(1))
    fireEvent.click(screen.getByRole('button', { name: opener }))
    expect(screen.getByTestId(testId)).toBeInTheDocument()

    fireEvent.keyDown(document.body, { key: 'Escape' })
    fireEvent.keyDown(document.body, { key: 'Enter' })

    expect(navigated()).toBe(0)
  })

  it('Escape with a one-entry history goes to the library instead of a no-op back', () => {
    setHistoryLength(1)
    render(<GalleryDetailPage />)

    fireEvent.keyDown(document.body, { key: 'Escape' })

    expect(h.back).not.toHaveBeenCalled()
    expect(h.push).toHaveBeenCalledWith('/library')
  })

  it('Escape on a page reached by a nav-tab restore climbs to the library list', () => {
    window.history.replaceState({}, '', '/library/ehentai/123')
    rememberLocation(['/library'], '/library', 'q=glasses')
    markTabRestore('/library/ehentai/123')
    render(<GalleryDetailPage />)

    fireEvent.keyDown(document.body, { key: 'Escape' })

    expect(h.back).not.toHaveBeenCalled()
    expect(h.replace).toHaveBeenCalledWith('/library?q=glasses')
  })
})

describe('library detail page error state', () => {
  beforeEach(() => {
    h.gallery = undefined
    h.error = new Error('boom')
    setHistoryLength(1)
  })

  it('error state: the inline back button resolves through smartBack, not a bare router.back()', () => {
    render(<GalleryDetailPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Go back' }))

    expect(h.back).not.toHaveBeenCalled()
    expect(h.push).toHaveBeenCalledWith('/library')
  })

  it('error state carries the fixed back control', () => {
    render(<GalleryDetailPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Back' }))

    expect(h.push).toHaveBeenCalledWith('/library')
  })
})
