/**
 * Regression tests: Explorer page handles API errors without crashing.
 *
 * Bug: when useSWR returned an error, the explorer page would propagate the
 * error up and trigger the nearest ErrorBoundary rather than rendering an
 * inline error UI with a retry button. The fix adds a dedicated error branch
 * in the render function that displays the error message and a retry button.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { api } from '@/lib/api'

// ── Mock next/navigation ──────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/explorer',
}))

// ── Mock @/lib/i18n: return the key so assertions are stable ─────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

// ── Mock @/lib/api to avoid import-time side effects ─────────────────

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      listFiles: vi.fn(),
      listGalleryFiles: vi.fn(),
      batchGalleries: vi.fn(),
      deleteImage: vi.fn(),
      deleteGallery: vi.fn(),
    },
  },
}))

// ── Mock sonner (toast) ───────────────────────────────────────────────

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// ── Mock @/components/Skeleton ────────────────────────────────────────

vi.mock('@/components/Skeleton', () => ({
  SkeletonGrid: () => <div data-testid="skeleton-grid" />,
}))

// ── SWR mock with per-test-controlled responses ───────────────────────

const mockMutate = vi.fn()
let swrResponses: Record<string, unknown> = {}

vi.mock('swr', () => ({
  default: (key: unknown, fetcher?: () => unknown) => {
    // The explorer page uses array keys like ['explorer-dirs', ...].
    // Match on the first element of the array.
    const keyStr = Array.isArray(key) ? String(key[0]) : key === null ? '__null__' : String(key)
    if (key !== null && keyStr === 'explorer-dirs' && fetcher) void fetcher()
    return (
      (swrResponses[keyStr] as object) ?? {
        data: undefined,
        error: undefined,
        isLoading: true,
        mutate: mockMutate,
      }
    )
  },
}))

// ── Tests ─────────────────────────────────────────────────────────────

describe('ExplorerPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    swrResponses = {}
  })

  it('test_explorer_renders_empty_state_with_no_data', async () => {
    swrResponses = {
      'explorer-dirs': {
        data: { directories: [], total: 0, page: 0 },
        error: undefined,
        isLoading: false,
        mutate: mockMutate,
      },
    }

    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    // With empty directories the SourceView shows the noSources message.
    // No ErrorBoundary should be triggered.
    expect(screen.getByText('explorer.noSources')).toBeDefined()
    expect(screen.queryByText('common.errorOccurred')).toBeNull()
  })

  it('test_explorer_shows_error_ui_on_api_failure', async () => {
    swrResponses = {
      'explorer-dirs': {
        data: undefined,
        error: new Error('Network error'),
        isLoading: false,
        mutate: mockMutate,
      },
    }

    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    // The inline error UI should display the error message and a retry button.
    expect(screen.getByText('Network error')).toBeDefined()
    expect(screen.getByText('common.retry')).toBeDefined()
  })

  it('test_explorer_retry_button_refetches_on_error', async () => {
    swrResponses = {
      'explorer-dirs': {
        data: undefined,
        error: new Error('Network error'),
        isLoading: false,
        mutate: mockMutate,
      },
    }

    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    const retryButton = screen.getByText('common.retry')
    fireEvent.click(retryButton)

    // Clicking retry should call the SWR mutate function to re-fetch.
    expect(mockMutate).toHaveBeenCalledTimes(1)
  })

  it('test_explorer_displays_local_link_and_copy_source_groups', async () => {
    swrResponses = {
      'explorer-dirs': {
        data: {
          directories: [
            {
              gallery_id: 1,
              source_id: 'linked',
              title: 'Linked Gallery',
              category: null,
              file_count: 2,
              rating: 0,
              favorited: false,
              is_favorited: false,
              my_rating: 0,
              source: 'local',
              import_mode: 'link',
              disk_size: 200,
            },
            {
              gallery_id: 2,
              source_id: 'copied',
              title: 'Copied Gallery',
              category: null,
              file_count: 3,
              rating: 0,
              favorited: false,
              is_favorited: false,
              my_rating: 0,
              source: 'local',
              import_mode: 'copy',
              disk_size: 300,
            },
          ],
          total: 2,
          page: 0,
        },
        error: undefined,
        isLoading: false,
        mutate: mockMutate,
      },
    }

    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(screen.getByText('explorer.externalFolders')).toBeDefined()
    expect(screen.getByText('explorer.jyzroxImport')).toBeDefined()
  })

  it('test_explorer_groups_local_galleries_without_artist_under_uncategorized', async () => {
    swrResponses = {
      'explorer-dirs': {
        data: {
          directories: [
            {
              gallery_id: 1,
              source_id: 'linked',
              title: 'Linked Gallery',
              category: null,
              file_count: 2,
              rating: 0,
              favorited: false,
              is_favorited: false,
              my_rating: 0,
              source: 'local',
              import_mode: 'link',
              artist_id: null,
              uploader: null,
              disk_size: 200,
            },
          ],
          total: 1,
          page: 0,
        },
        error: undefined,
        isLoading: false,
        mutate: mockMutate,
      },
    }

    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.doubleClick(screen.getByText('explorer.externalFolders'))

    expect(screen.getByText('explorer.uncategorizedArtist')).toBeDefined()
    expect(screen.getByText('Linked Gallery')).toBeDefined()
  })

  it('test_explorer_queries_local_link_with_import_mode_filter', async () => {
    swrResponses = {
      'explorer-dirs': {
        data: {
          directories: [
            {
              gallery_id: 1,
              source_id: 'linked',
              title: 'Linked Gallery',
              category: null,
              file_count: 2,
              rating: 0,
              favorited: false,
              is_favorited: false,
              my_rating: 0,
              source: 'local',
              import_mode: 'link',
              disk_size: 200,
            },
          ],
          total: 1,
          page: 0,
        },
        error: undefined,
        isLoading: false,
        mutate: mockMutate,
      },
    }

    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.doubleClick(screen.getByText('explorer.externalFolders'))

    expect(api.library.listFiles).toHaveBeenLastCalledWith({
      q: undefined,
      source: 'local',
      import_mode: 'link',
      page: 0,
      limit: 50,
    })
  })
})
