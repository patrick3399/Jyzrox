/**
 * Regression test: React hooks order violation in GalleryDetailPage
 *
 * Bug: useMemo was called AFTER early returns (galleryLoading, galleryError,
 * !gallery). When the component first renders with isLoading=true it returns
 * early before reaching the useMemo call. On the next render, gallery data
 * arrives and the component no longer returns early, so useMemo is called for
 * the first time. React sees a different number of hooks between renders and
 * throws Error #310 (hooks order violation).
 *
 * Fix: useMemo was moved to before the early returns so the hook is called on
 * every render regardless of loading/error state.
 *
 * This test exercises the exact transition that triggered the bug:
 *   loading=true  (first render)  → early return, useMemo not reached
 *   loading=false (second render) → gallery rendered, useMemo now reachable
 *
 * The test asserts that this transition does NOT throw.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render } from '@testing-library/react'

// ── Hoisted mock factories ──────────────────────────────────────────────

const {
  mockUseLibraryGallery,
  mockUseGalleryImages,
  mockUseUpdateGallery,
  mockUseTagTranslations,
  mockGetGalleryTags,
} = vi.hoisted(() => ({
  mockUseLibraryGallery: vi.fn(),
  mockUseGalleryImages: vi.fn(),
  mockUseUpdateGallery: vi.fn(),
  mockUseTagTranslations: vi.fn(),
  mockGetGalleryTags: vi.fn(),
}))

// ── Module mocks ────────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ source: 'ehentai', sourceId: '99999' }),
}))

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
  formatDate: (d: string) => d,
  formatBytes: (n: number) => String(n),
  SUPPORTED_LOCALES: ['en'],
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'en', setLocale: vi.fn() }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      checkUpdate: vi.fn().mockResolvedValue({ status: 'no_change' }),
      getGalleryTags: mockGetGalleryTags,
      deleteGallery: vi.fn().mockResolvedValue({}),
      deleteImage: vi.fn().mockResolvedValue({}),
      listExcluded: vi.fn().mockResolvedValue({ excluded: [] }),
      restoreExcluded: vi.fn().mockResolvedValue({}),
    },
    settings: {
      getFeatures: vi.fn().mockResolvedValue({}),
    },
    history: {
      record: vi.fn().mockResolvedValue({}),
    },
    tags: {
      updateGalleryTags: vi.fn().mockResolvedValue({ status: 'ok', affected: 1 }),
      retag: vi.fn().mockResolvedValue({ status: 'ok', gallery_id: 1 }),
    },
  },
}))

vi.mock('@/hooks/useGalleries', () => ({
  useLibraryGallery: mockUseLibraryGallery,
  useGalleryImages: mockUseGalleryImages,
  useUpdateGallery: mockUseUpdateGallery,
}))

vi.mock('@/hooks/useTagTranslations', () => ({
  useTagTranslations: mockUseTagTranslations,
}))

// SWR: return undefined data immediately (simulates feature settings loading)
vi.mock('swr', () => ({
  default: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    error: undefined,
    mutate: vi.fn(),
  })),
  mutate: vi.fn(),
}))

// Stub heavy child components
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}))

vi.mock('@/components/RatingStars', () => ({
  RatingStars: () => <div data-testid="rating-stars" />,
}))

vi.mock('@/components/BackButton', () => ({
  BackButton: () => <button data-testid="back-button">Back</button>,
}))

vi.mock('@/components/TagAutocomplete', () => ({
  TagAutocomplete: ({ placeholder }: { placeholder?: string }) => (
    <input data-testid="tag-autocomplete" placeholder={placeholder ?? 'autocomplete'} />
  ),
}))

// ── Import component under test after all mocks are registered ──────────

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'

// ── Test data factory ───────────────────────────────────────────────────

function makeGallery(overrides: Record<string, unknown> = {}) {
  return {
    id: 99,
    title: 'Regression Test Gallery',
    source: 'ehentai',
    source_id: '99999',
    download_status: 'complete',
    tags_array: ['artist:regression', 'general:test'],
    added_at: new Date().toISOString(),
    ...overrides,
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────

type GalleryHookState = {
  data: ReturnType<typeof makeGallery> | undefined
  isLoading: boolean
  error: Error | null
  mutate: ReturnType<typeof vi.fn>
}

const loadingState: GalleryHookState = { data: undefined, isLoading: true, error: null, mutate: vi.fn() }

function dataState(gallery?: ReturnType<typeof makeGallery>): GalleryHookState {
  return { data: gallery ?? makeGallery(), isLoading: false, error: null, mutate: vi.fn() }
}

function errorState(msg = 'Network failure'): GalleryHookState {
  return { data: undefined, isLoading: false, error: new Error(msg), mutate: vi.fn() }
}

/** Render with phase1 state, then rerender with phase2 state; assert no throw. */
function expectTransitionDoesNotThrow(phase1: GalleryHookState, phase2: GalleryHookState) {
  mockUseLibraryGallery.mockReturnValue(phase1)
  const { rerender } = render(<GalleryDetailPage />)
  mockUseLibraryGallery.mockReturnValue(phase2)
  expect(() => rerender(<GalleryDetailPage />)).not.toThrow()
}

// ── Setup ───────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockGetGalleryTags.mockResolvedValue({ tags: [] })

  mockUseGalleryImages.mockReturnValue({
    data: { images: [] },
    isLoading: false,
    mutate: vi.fn(),
  })

  mockUseUpdateGallery.mockReturnValue({
    trigger: vi.fn().mockResolvedValue(makeGallery()),
    isMutating: false,
  })

  mockUseTagTranslations.mockReturnValue({
    data: {},
    isLoading: false,
  })
})

// ── Regression tests ────────────────────────────────────────────────────

describe('GalleryDetailPage — hooks order regression', () => {
  /**
   * Core regression: simulate the loading → data-available transition.
   * Before the fix, useMemo was only reached after the early returns,
   * causing React Error #310 when the hook count changed between renders.
   */
  it('test_gallery_detail_loading_to_loaded_transition_does_not_throw_hooks_error', () => {
    expectTransitionDoesNotThrow(loadingState, dataState())
  })

  /**
   * Baseline: gallery data available from the very first render (no loading phase).
   */
  it('test_gallery_detail_with_data_on_first_render_does_not_throw', () => {
    mockUseLibraryGallery.mockReturnValue(dataState())
    expect(() => render(<GalleryDetailPage />)).not.toThrow()
  })

  /**
   * Edge case: gallery with populated tags_array exercises the useMemo
   * that builds manualTagSet.
   */
  it('test_gallery_detail_with_tags_does_not_throw_hook_error_on_data_load', () => {
    const gallery = makeGallery({
      tags_array: ['artist:foo', 'character:bar', 'female:baz', 'general:test'],
    })
    expectTransitionDoesNotThrow(loadingState, dataState(gallery))
  })

  /**
   * Error path: loading → error transition covers the galleryError early
   * return branch, ensuring hook count stability across all early returns.
   */
  it('test_gallery_detail_loading_to_error_transition_does_not_throw_hooks_error', () => {
    expectTransitionDoesNotThrow(loadingState, errorState())
  })
})
