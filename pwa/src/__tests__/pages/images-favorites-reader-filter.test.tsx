import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { api } from '@/lib/api'
import FavoriteReaderPage from '@/app/reader/favorites/page'
import ImageBrowserPage from '@/app/images/page'

/**
 * Regression: opening an image from /images in favourites mode dropped the
 * source and category filters.
 *
 * The grid was filtered, but the click handler built `/reader/favorites` with
 * only `image_id` and `start`, and the favourites reader refetched with just
 * `favorited: true`. The Reader therefore paged through every favourite, in
 * every category, no matter what the grid was showing.
 */

const push = vi.fn()
const replace = vi.fn()
let search = ''

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push, replace }),
  useSearchParams: () => new URLSearchParams(search),
}))

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

vi.mock('@/components/Reader', () => ({
  default: () => <div data-testid="reader" />,
}))

vi.mock('@/components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/components/JustifiedGrid', () => ({
  JustifiedGrid: ({
    items,
    renderItem,
  }: {
    items: { id: number }[]
    renderItem: (
      item: { id: number },
      geometry: { width: number; height: number },
    ) => React.ReactNode
  }) => (
    <div>
      {items.map((item) => (
        <div key={item.id} data-testid={`cell-${item.id}`}>
          {renderItem(item, { width: 100, height: 100 })}
        </div>
      ))}
    </div>
  ),
}))

vi.mock('@/components/AppImage', () => ({ AppImage: () => null }))
vi.mock('@/components/TimelineScrubber', () => ({ TimelineScrubber: () => null }))
vi.mock('@/components/Reader/ImageContextMenu', () => ({ ImageContextMenu: () => null }))
vi.mock('@/components/LazyDialogs', () => ({ LazySauceNaoModal: () => null }))

const browseImage = {
  id: 5,
  gallery_id: 1,
  page_num: 3,
  width: 100,
  height: 150,
  thumb_path: '/media/thumbs/a/thumb_160.webp',
  file_path: '/media/cas/a.jpg',
  thumbhash: null,
  media_type: 'image' as const,
  added_at: '2026-10-01T00:00:00Z',
  source: 'ehentai',
  source_id: '123',
}

vi.mock('@/hooks/useImageBrowser', () => ({
  useImageBrowser: () => ({
    images: [browseImage],
    favoritedImageIds: new Set([5]),
    mutate: vi.fn(),
    isLoading: false,
    isLoadingMore: false,
    isReachingEnd: true,
    loadMore: vi.fn(),
  }),
}))

vi.mock('@/hooks/useTimeRange', () => ({
  useTimeRange: () => ({ minAt: null, maxAt: null }),
  useTimelinePercentiles: () => ({ percentiles: [] }),
}))

vi.mock('@/hooks/useGalleries', () => ({
  useLibrarySources: () => ({ data: undefined }),
  useGalleryCategories: () => ({ data: undefined }),
}))

vi.mock('@/hooks/useThumbhash', () => ({ useThumbhash: () => new Map() }))

vi.mock('@/lib/api', () => ({
  api: { library: { browseImages: vi.fn(), deleteImage: vi.fn() } },
}))

const browseImages = (api as unknown as { library: { browseImages: ReturnType<typeof vi.fn> } })
  .library.browseImages

class ImmediateResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe() {
    this.callback(
      [{ contentRect: { width: 1000 } } as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    )
  }
  unobserve() {}
  disconnect() {}
}

describe('favourites reader keeps the /images filters', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('ResizeObserver', ImmediateResizeObserver)
    browseImages.mockResolvedValue({
      images: [browseImage],
      next_cursor: null,
      has_next: false,
      favorited_image_ids: [5],
    })
  })

  it('favourites reader loads only the category and source named in its URL', async () => {
    search = 'image_id=5&start=1&category=Cosplay&source=ehentai'

    render(<FavoriteReaderPage />)

    await screen.findByTestId('reader')
    expect(browseImages).toHaveBeenCalledWith(
      expect.objectContaining({ favorited: true, category: 'Cosplay', source: 'ehentai' }),
    )
  })

  it('favourites reader loads every favourite when its URL names no filter', async () => {
    search = 'image_id=5&start=1'

    render(<FavoriteReaderPage />)

    await screen.findByTestId('reader')
    const params = browseImages.mock.calls[0][0]
    expect(params.favorited).toBe(true)
    expect(params.category).toBeUndefined()
    expect(params.source).toBeUndefined()
  })

  it('clicking a favourite with a category and source filter carries both into the reader URL', async () => {
    search = 'category=Cosplay&source=ehentai'

    render(<ImageBrowserPage />)

    const cell = await screen.findByTestId('cell-5')
    fireEvent.click(cell.querySelector('button') as HTMLButtonElement)

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1))
    const target = new URL(push.mock.calls[0][0], 'http://localhost')
    expect(target.pathname).toBe('/reader/favorites')
    expect(target.searchParams.get('image_id')).toBe('5')
    expect(target.searchParams.get('category')).toBe('Cosplay')
    expect(target.searchParams.get('source')).toBe('ehentai')
  })
})
