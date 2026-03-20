/**
 * Regression test: gallery detail page should remember favorite state
 * when navigated from the favorites list (?fav=1 query param).
 *
 * Bug: isFavorited was always initialised as false, so galleries opened
 * from the favorites tab showed an unfavorited heart icon.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// ── Mock next/navigation ─────────────────────────────────────────────

let mockSearchParams = new URLSearchParams()

vi.mock('next/navigation', () => ({
  useParams: () => ({ gid: '12345', token: 'abc123' }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => mockSearchParams,
}))

// ── Mock SWR hooks (return null data so we hit the loading/skeleton path) ──

vi.mock('@/hooks/useGalleries', () => ({
  useEhGallery: () => ({
    data: {
      gid: 12345,
      token: 'abc123',
      title: 'Test Gallery',
      title_jpn: '',
      category: 'Doujinshi',
      thumb: '',
      uploader: 'test',
      posted_at: 1700000000,
      pages: 10,
      rating: 4.5,
      tags: [],
      expunged: false,
    },
    error: undefined,
  }),
  useEhGalleryPreviews: () => ({ data: null }),
  useEhGalleryComments: () => ({ data: null, isLoading: false }),
  useEhGalleryImagesPaginated: () => ({
    getToken: () => null,
    getPreview: () => null,
    ensureRange: vi.fn(),
    isLoading: false,
  }),
}))

vi.mock('@/hooks/useTagTranslations', () => ({
  useTagTranslations: () => ({ translateTag: (t: string) => t }),
}))

vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      addFavorite: vi.fn(),
      removeFavorite: vi.fn(),
      getPreviews: vi.fn(),
    },
    history: { recordBrowse: vi.fn().mockResolvedValue({}) },
  },
}))

vi.mock('dompurify', () => ({
  default: { sanitize: (s: string) => s },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))

vi.mock('@/components/RatingStars', () => ({
  RatingStars: ({ rating }: { rating: number }) => <span data-testid="rating">{rating}</span>,
}))

vi.mock('@/components/BackButton', () => ({
  BackButton: () => <button data-testid="back">Back</button>,
}))

// ── Tests ────────────────────────────────────────────────────────────

describe('EhGalleryDetailPage favorite state from URL', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
  })

  it('initialises isFavorited=true when ?fav=1 is present', async () => {
    mockSearchParams = new URLSearchParams('fav=1')

    const { default: Page } = await import('@/app/e-hentai/[gid]/[token]/page')
    render(<Page />)

    // The filled heart ♥ indicates favorited state
    const favButton = await screen.findByText('♥')
    expect(favButton).toBeDefined()
  })

  it('initialises isFavorited=false when ?fav is absent', async () => {
    mockSearchParams = new URLSearchParams()

    // Force re-import to pick up new searchParams
    vi.resetModules()

    // Re-apply mocks after resetModules
    vi.doMock('next/navigation', () => ({
      useParams: () => ({ gid: '12345', token: 'abc123' }),
      useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
      useSearchParams: () => mockSearchParams,
    }))
    vi.doMock('@/hooks/useGalleries', () => ({
      useEhGallery: () => ({
        data: {
          gid: 12345,
          token: 'abc123',
          title: 'Test Gallery',
          title_jpn: '',
          category: 'Doujinshi',
          thumb: '',
          uploader: 'test',
          posted_at: 1700000000,
          pages: 10,
          rating: 4.5,
          tags: [],
          expunged: false,
        },
        error: undefined,
      }),
      useEhGalleryPreviews: () => ({ data: null }),
      useEhGalleryComments: () => ({ data: null, isLoading: false }),
      useEhGalleryImagesPaginated: () => ({
        getToken: () => null,
        getPreview: () => null,
        ensureRange: vi.fn(),
        isLoading: false,
      }),
    }))
    vi.doMock('@/hooks/useTagTranslations', () => ({
      useTagTranslations: () => ({ translateTag: (t: string) => t }),
    }))
    vi.doMock('@/lib/api', () => ({
      api: {
        eh: { addFavorite: vi.fn(), removeFavorite: vi.fn(), getPreviews: vi.fn() },
        history: { recordBrowse: vi.fn().mockResolvedValue({}) },
      },
    }))
    vi.doMock('dompurify', () => ({ default: { sanitize: (s: string) => s } }))
    vi.doMock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
    vi.doMock('@/components/LoadingSpinner', () => ({
      LoadingSpinner: () => <div data-testid="spinner" />,
    }))
    vi.doMock('@/components/RatingStars', () => ({
      RatingStars: ({ rating }: { rating: number }) => <span data-testid="rating">{rating}</span>,
    }))
    vi.doMock('@/components/BackButton', () => ({
      BackButton: () => <button data-testid="back">Back</button>,
    }))

    const { default: Page } = await import('@/app/e-hentai/[gid]/[token]/page')
    render(<Page />)

    // The empty heart ♡ indicates not-favorited state
    const unfavButton = await screen.findByText('♡')
    expect(unfavButton).toBeDefined()
  })
})
