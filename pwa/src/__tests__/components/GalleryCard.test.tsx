/**
 * GalleryCard (LibraryGalleryCard) — Vitest test suite
 *
 * Covers:
 *   - Title rendering
 *   - Thumbnail img display
 *   - Category placeholder when no thumb
 *   - Source badge
 *   - Favourite indicator
 *   - Download status indicator
 *   - SelectMode checkbox overlay
 *   - Selected state border
 *   - Click/navigation behavior (role="button")
 *   - No role="button" without onClick
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import type { Gallery } from '@/lib/types'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const { mockGetSourceStyle, mockGetEventPosition, mockUseLongPress, mockUseRouter } = vi.hoisted(
  () => ({
    mockGetSourceStyle: vi.fn(),
    mockGetEventPosition: vi.fn(() => ({ x: 0, y: 0 })),
    mockUseLongPress: vi.fn(() => ({})),
    mockUseRouter: vi.fn(() => ({ push: vi.fn() })),
  }),
)

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/lib/galleryUtils', () => ({
  getSourceStyle: mockGetSourceStyle,
  getEventPosition: mockGetEventPosition,
}))

vi.mock('@/components/RatingStars', () => ({
  RatingStars: () => <span data-testid="rating-stars" />,
}))

vi.mock('@/components/ContextMenu', () => ({
  ContextMenu: () => null,
}))

vi.mock('@/hooks/useLongPress', () => ({
  useLongPress: mockUseLongPress,
}))

vi.mock('next/navigation', () => ({
  useRouter: mockUseRouter,
}))

// ── Import component after mocks ───────────────────────────────────────

import { LibraryGalleryCard } from '@/components/GalleryCard'

// ── Gallery factory ────────────────────────────────────────────────────

function makeGallery(overrides: Partial<Gallery> = {}): Gallery {
  return {
    id: 1,
    source: 'local',
    source_id: '001',
    title: 'Test Gallery',
    title_jpn: '',
    category: 'Doujinshi',
    language: 'English',
    pages: 20,
    posted_at: null,
    added_at: '2024-01-01T00:00:00Z',
    rating: 3,
    favorited: false,
    is_favorited: false,
    my_rating: null,
    in_reading_list: false,
    uploader: '',
    artist_id: null,
    download_status: 'complete',
    import_mode: null,
    tags_array: [],
    ...overrides,
  }
}

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockGetSourceStyle.mockReturnValue({ label: 'Local', className: 'bg-green-900/50' })
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('LibraryGalleryCard', () => {
  describe('title rendering', () => {
    it('test_libraryGalleryCard_withTitle_rendersTitle', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ title: 'My Gallery' })} />)
      expect(screen.getByText('My Gallery')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_noTitle_fallsBackToTitleJpn', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ title: '', title_jpn: 'Japanese Title' })} />)
      expect(screen.getByText('Japanese Title')).toBeInTheDocument()
    })
  })

  describe('thumbnail', () => {
    it('test_libraryGalleryCard_withThumbUrl_rendersImg', () => {
      render(<LibraryGalleryCard gallery={makeGallery()} thumbUrl="https://example.com/cover.jpg" />)
      const img = screen.getByRole('img')
      expect(img).toBeInTheDocument()
      expect(img).toHaveAttribute('src', 'https://example.com/cover.jpg')
    })

    it('test_libraryGalleryCard_withThumbUrl_imgAltIsTitle', () => {
      render(
        <LibraryGalleryCard
          gallery={makeGallery({ title: 'Cover Gallery' })}
          thumbUrl="https://example.com/cover.jpg"
        />,
      )
      expect(screen.getByRole('img')).toHaveAttribute('alt', 'Cover Gallery')
    })

    it('test_libraryGalleryCard_noThumbUrl_doesNotRenderImg', () => {
      render(<LibraryGalleryCard gallery={makeGallery()} />)
      expect(screen.queryByRole('img')).not.toBeInTheDocument()
    })

    it('test_libraryGalleryCard_noThumbUrl_showsCategoryText', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ category: 'Manga' })} />)
      expect(screen.getByText('Manga')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_noThumbUrlNoCategory_showsFallbackKey', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ category: '' })} />)
      expect(screen.getByText('library.categoryUncategorized')).toBeInTheDocument()
    })
  })

  describe('source badge', () => {
    it('test_libraryGalleryCard_localSource_showsLocalLabel', () => {
      mockGetSourceStyle.mockReturnValue({ label: 'Local', className: '' })
      render(<LibraryGalleryCard gallery={makeGallery({ source: 'local' })} />)
      expect(screen.getByText('Local')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_ehentaiSource_showsEHentaiLabel', () => {
      mockGetSourceStyle.mockReturnValue({ label: 'E-Hentai', className: '' })
      render(<LibraryGalleryCard gallery={makeGallery({ source: 'ehentai' })} />)
      expect(screen.getByText('E-Hentai')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_sourceBadge_callsGetSourceStyleWithGallery', () => {
      const gallery = makeGallery()
      render(<LibraryGalleryCard gallery={gallery} />)
      expect(mockGetSourceStyle).toHaveBeenCalledWith(gallery)
    })
  })

  describe('favourite indicator', () => {
    it('test_libraryGalleryCard_isFavoritedTrue_showsHeartSymbol', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ is_favorited: true })} />)
      expect(screen.getByLabelText('common.favourited')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_isFavoritedTrue_heartSymbolContainsHeart', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ is_favorited: true })} />)
      expect(screen.getByLabelText('common.favourited').textContent).toBe('♥')
    })

    it('test_libraryGalleryCard_isFavoritedFalse_doesNotShowHeart', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ is_favorited: false })} />)
      expect(screen.queryByLabelText('common.favourited')).not.toBeInTheDocument()
    })
  })

  describe('download status indicator', () => {
    it('test_libraryGalleryCard_downloadingStatusNoSelectMode_showsBadge', () => {
      render(
        <LibraryGalleryCard
          gallery={makeGallery({ download_status: 'downloading' })}
          selectMode={false}
        />,
      )
      expect(screen.getByText('queue.downloading')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_downloadingStatusSelectModeTrue_hidesBadge', () => {
      render(
        <LibraryGalleryCard
          gallery={makeGallery({ download_status: 'downloading' })}
          selectMode={true}
        />,
      )
      expect(screen.queryByText('queue.downloading')).not.toBeInTheDocument()
    })

    it('test_libraryGalleryCard_completeStatus_doesNotShowBadge', () => {
      render(
        <LibraryGalleryCard
          gallery={makeGallery({ download_status: 'complete' })}
          selectMode={false}
        />,
      )
      expect(screen.queryByText('queue.downloading')).not.toBeInTheDocument()
    })
  })

  describe('selectMode checkbox overlay', () => {
    it('test_libraryGalleryCard_selectModeTrue_rendersCheckboxOverlay', () => {
      const { container } = render(
        <LibraryGalleryCard gallery={makeGallery()} selectMode={true} />,
      )
      const overlay = container.querySelector('.absolute.top-1\\.5.left-1\\.5.z-10')
      expect(overlay).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_selectModeFalse_doesNotRenderCheckboxOverlay', () => {
      // Without selectMode there should be no checkbox div (only potentially the download badge div)
      const { container } = render(
        <LibraryGalleryCard
          gallery={makeGallery({ download_status: 'complete' })}
          selectMode={false}
        />,
      )
      // The checkbox is a div>div structure with w-5 h-5 classes
      const checkboxInner = container.querySelector('.w-5.h-5.rounded.border-2')
      expect(checkboxInner).not.toBeInTheDocument()
    })

    it('test_libraryGalleryCard_selectedTrue_rendersCheckmark', () => {
      const { container } = render(
        <LibraryGalleryCard gallery={makeGallery()} selectMode={true} selected={true} />,
      )
      const checkmark = container.querySelector('.text-xs')
      expect(checkmark).toBeInTheDocument()
      expect(checkmark!.textContent).toBe('✓')
    })
  })

  describe('article role', () => {
    it('test_libraryGalleryCard_withOnClick_articleHasButtonRole', () => {
      render(<LibraryGalleryCard gallery={makeGallery()} onClick={vi.fn()} />)
      expect(screen.getByRole('button')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_withoutOnClick_articleHasNoButtonRole', () => {
      render(<LibraryGalleryCard gallery={makeGallery()} />)
      expect(screen.queryByRole('button')).not.toBeInTheDocument()
    })
  })

  describe('ratings', () => {
    it('test_libraryGalleryCard_rendersRatingStars', () => {
      render(<LibraryGalleryCard gallery={makeGallery()} />)
      expect(screen.getByTestId('rating-stars')).toBeInTheDocument()
    })

    it('test_libraryGalleryCard_rendersPageCount', () => {
      render(<LibraryGalleryCard gallery={makeGallery({ pages: 42 })} />)
      expect(screen.getByText('42p')).toBeInTheDocument()
    })
  })
})
