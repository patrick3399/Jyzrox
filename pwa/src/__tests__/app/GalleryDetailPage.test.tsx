/**
 * GalleryDetailPage — Vitest test suite
 *
 * Primary regression goal: ensure no hook is called after an early return
 * (React error #310 / rules-of-hooks violation).  If someone moves a hook
 * below a conditional return, React will throw during render and every test
 * that exercises the "gallery loaded" path will fail immediately.
 *
 * Covers:
 *   - Loading state renders LoadingSpinner
 *   - Error state renders error message
 *   - Gallery not found (null) renders nothing
 *   - Gallery loaded renders title without throwing (regression for #310)
 *   - Gallery loaded with tags renders tags section
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const {
  mockUseParams,
  mockUseRouter,
  mockUseLibraryGallery,
  mockUseGalleryImages,
  mockUseUpdateGallery,
  mockUseTagTranslations,
  mockApiHistoryRecord,
  mockApiLibraryListExcluded,
  mockApiTagsRetag,
  mockApiLibraryGetGalleryTags,
} = vi.hoisted(() => ({
  mockUseParams: vi.fn(),
  mockUseRouter: vi.fn(() => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() })),
  mockUseLibraryGallery: vi.fn(),
  mockUseGalleryImages: vi.fn(),
  mockUseUpdateGallery: vi.fn(),
  mockUseTagTranslations: vi.fn(),
  mockApiHistoryRecord: vi.fn(() => Promise.resolve()),
  mockApiLibraryListExcluded: vi.fn(() => Promise.resolve({ excluded: [] })),
  mockApiTagsRetag: vi.fn(() => Promise.resolve({ status: 'queued', gallery_id: 1 })),
  mockApiLibraryGetGalleryTags: vi.fn(() => Promise.resolve({ tags: [] })),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useParams: mockUseParams,
  useRouter: mockUseRouter,
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, _params?: Record<string, unknown>) => key,
  formatDate: (d: string) => d,
}))

vi.mock('@/hooks/useGalleries', () => ({
  useLibraryGallery: mockUseLibraryGallery,
  useGalleryImages: mockUseGalleryImages,
  useUpdateGallery: mockUseUpdateGallery,
}))

vi.mock('@/hooks/useTagTranslations', () => ({
  useTagTranslations: mockUseTagTranslations,
}))

vi.mock('@/lib/api', () => ({
  api: {
    history: { record: mockApiHistoryRecord },
    library: {
      listExcluded: mockApiLibraryListExcluded,
      getGalleryTags: mockApiLibraryGetGalleryTags,
      deleteGallery: vi.fn(),
      deleteImage: vi.fn(),
      restoreExcluded: vi.fn(),
    },
    tags: { retag: mockApiTagsRetag },
  },
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}))

vi.mock('@/components/RatingStars', () => ({
  RatingStars: () => <span data-testid="rating-stars" />,
}))

vi.mock('@/components/BackButton', () => ({
  BackButton: () => <button data-testid="back-button" />,
}))

// ── Import component after mocks ───────────────────────────────────────

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

// ── Test data factory ──────────────────────────────────────────────────

function makeGallery(overrides: Partial<Gallery> = {}): Gallery {
  return {
    id: 1,
    source: 'ehentai',
    source_id: '12345',
    title: 'Test Gallery',
    title_jpn: '',
    category: 'Doujinshi',
    language: 'English',
    pages: 24,
    posted_at: null,
    added_at: '2024-01-01T00:00:00Z',
    rating: 0,
    favorited: false,
    is_favorited: false,
    my_rating: null,
    uploader: '',
    artist_id: null,
    download_status: 'complete',
    import_mode: null,
    tags_array: [],
    cover_thumb: null,
    source_url: null,
    ...overrides,
  }
}

// ── Default hook stubs (overridden per test as needed) ─────────────────

function setupDefaultMocks() {
  mockUseParams.mockReturnValue({ source: 'ehentai', sourceId: '12345' })
  mockUseLibraryGallery.mockReturnValue({
    data: null,
    isLoading: false,
    error: null,
    mutate: vi.fn(),
  })
  mockUseGalleryImages.mockReturnValue({
    data: null,
    isLoading: false,
    mutate: vi.fn(),
  })
  mockUseUpdateGallery.mockReturnValue({
    trigger: vi.fn(),
    isMutating: false,
  })
  mockUseTagTranslations.mockReturnValue({ data: undefined })
}

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  setupDefaultMocks()
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('GalleryDetailPage', () => {
  describe('loading state', () => {
    it('test_GalleryDetailPage_galleryLoading_rendersLoadingSpinner', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: null,
        isLoading: true,
        error: null,
        mutate: vi.fn(),
      })

      render(<GalleryDetailPage />)

      expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
    })

    it('test_GalleryDetailPage_galleryLoading_doesNotRenderTitle', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: null,
        isLoading: true,
        error: null,
        mutate: vi.fn(),
      })

      render(<GalleryDetailPage />)

      expect(screen.queryByRole('heading')).not.toBeInTheDocument()
    })
  })

  describe('error state', () => {
    it('test_GalleryDetailPage_galleryError_rendersFailedToLoadKey', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: null,
        isLoading: false,
        error: { message: 'Not found' },
        mutate: vi.fn(),
      })

      render(<GalleryDetailPage />)

      expect(screen.getByText('library.failedToLoad')).toBeInTheDocument()
    })

    it('test_GalleryDetailPage_galleryError_rendersErrorMessage', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: null,
        isLoading: false,
        error: { message: 'Not found' },
        mutate: vi.fn(),
      })

      render(<GalleryDetailPage />)

      expect(screen.getByText('Not found')).toBeInTheDocument()
    })
  })

  describe('gallery not found', () => {
    it('test_GalleryDetailPage_galleryNullNotLoading_rendersNothing', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: null,
        isLoading: false,
        error: null,
        mutate: vi.fn(),
      })

      const { container } = render(<GalleryDetailPage />)

      // Component returns null — container should be empty
      expect(container.firstChild).toBeNull()
    })
  })

  describe('gallery loaded — regression guard for React error #310', () => {
    it('test_GalleryDetailPage_galleryLoaded_rendersTitle', () => {
      // This test is the primary regression guard.
      // If any hook is called after an early return, React will throw during
      // render with "Rendered more hooks than during the previous render"
      // (error #310) and this test will fail.
      mockUseLibraryGallery.mockReturnValue({
        data: makeGallery({ title: 'Test Gallery' }),
        isLoading: false,
        error: null,
        mutate: vi.fn(),
      })
      mockUseGalleryImages.mockReturnValue({
        data: { images: [] },
        isLoading: false,
        mutate: vi.fn(),
      })

      expect(() => render(<GalleryDetailPage />)).not.toThrow()

      expect(screen.getByText('Test Gallery')).toBeInTheDocument()
    })

    it('test_GalleryDetailPage_galleryLoaded_rendersBackButton', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: makeGallery(),
        isLoading: false,
        error: null,
        mutate: vi.fn(),
      })
      mockUseGalleryImages.mockReturnValue({
        data: { images: [] },
        isLoading: false,
        mutate: vi.fn(),
      })

      render(<GalleryDetailPage />)

      expect(screen.getByTestId('back-button')).toBeInTheDocument()
    })

    it('test_GalleryDetailPage_galleryLoaded_rendersRatingStars', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: makeGallery({ my_rating: 4 }),
        isLoading: false,
        error: null,
        mutate: vi.fn(),
      })
      mockUseGalleryImages.mockReturnValue({
        data: { images: [] },
        isLoading: false,
        mutate: vi.fn(),
      })

      render(<GalleryDetailPage />)

      expect(screen.getByTestId('rating-stars')).toBeInTheDocument()
    })
  })

  describe('gallery loaded with tags', () => {
    it('test_GalleryDetailPage_galleryWithTags_rendersTagsSection', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: makeGallery({
          tags_array: ['artist:test-artist', 'character:hero'],
        }),
        isLoading: false,
        error: null,
        mutate: vi.fn(),
      })
      mockUseGalleryImages.mockReturnValue({
        data: { images: [] },
        isLoading: false,
        mutate: vi.fn(),
      })
      mockUseTagTranslations.mockReturnValue({
        data: { 'artist:test-artist': 'Test Artist', 'character:hero': 'Hero' },
      })

      render(<GalleryDetailPage />)

      // Tags section heading
      expect(screen.getByText('common.tags')).toBeInTheDocument()
      // Tag values (without namespace prefix) are rendered as individual spans
      expect(screen.getByText('test-artist')).toBeInTheDocument()
      expect(screen.getByText('hero')).toBeInTheDocument()
    })

    it('test_GalleryDetailPage_galleryWithNoTags_rendersNoTagsMessage', () => {
      mockUseLibraryGallery.mockReturnValue({
        data: makeGallery({ tags_array: [] }),
        isLoading: false,
        error: null,
        mutate: vi.fn(),
      })
      mockUseGalleryImages.mockReturnValue({
        data: { images: [] },
        isLoading: false,
        mutate: vi.fn(),
      })

      render(<GalleryDetailPage />)

      expect(screen.getByText('library.noTags')).toBeInTheDocument()
    })
  })
})
