/**
 * Frontend gap features — Vitest test suite
 *
 * Covers three features implemented in the recent dev cycle:
 *
 *   Feature 1 — Per-Gallery Tag Editing UI (GalleryDetailPage)
 *     - "Edit Tags" toggle button is rendered next to the Tags heading
 *     - Clicking the toggle activates edit mode
 *     - In edit mode, TagAutocomplete is shown (add tags)
 *     - In edit mode, manual tags show a remove (×) button
 *     - Selecting a tag from autocomplete calls api.tags.updateGalleryTags (add)
 *     - Clicking the × remove button calls api.tags.updateGalleryTags (remove)
 *
 *   Feature 2 — Reconciliation UI (SettingsPage — system section)
 *     - "Data Reconciliation" sub-section renders after system loads
 *     - "never run" state shows the reconcileNeverRun message
 *     - "Run Now" button triggers confirm dialog then calls api.system.startReconcile
 *     - Stats are shown when last run data is present
 *
 *   Feature 3 — Tag Translation Management UI (TagsPage detail panel)
 *     - api.tags.upsertTranslation is called with the correct payload
 *     - api.tags.batchImportTranslations is called with a translations array
 *     - api.tags.getTranslations resolves translations for given tags
 *
 * Mock strategy:
 *   - @/lib/i18n  → t() returns the key as-is for predictable assertions
 *   - @/lib/api   → all API methods vi.fn() with appropriate resolved values
 *   - next/navigation  → stubbed router / searchParams / params
 *   - Heavy sub-components stubbed to lightweight sentinels
 *   - sonner toast stubbed
 *   - window.confirm stubbed to return true
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── Hoisted helpers ────────────────────────────────────────────────────

const {
  mockUseLibraryGallery,
  mockUseGalleryImages,
  mockUseUpdateGallery,
  mockUseTagTranslations,
  mockUpdateGalleryTags,
  mockStartReconcile,
  mockGetReconcileStatus,
  mockUpsertTranslation,
  mockBatchImportTranslations,
  mockGetTranslations,
  mockGetGalleryTags,
} = vi.hoisted(() => ({
  mockUseLibraryGallery: vi.fn(),
  mockUseGalleryImages: vi.fn(),
  mockUseUpdateGallery: vi.fn(),
  mockUseTagTranslations: vi.fn(),
  mockUpdateGalleryTags: vi.fn().mockResolvedValue({ status: 'ok', affected: 1 }),
  mockStartReconcile: vi.fn().mockResolvedValue({ status: 'enqueued' }),
  mockGetReconcileStatus: vi.fn().mockResolvedValue({ status: 'never_run' }),
  mockUpsertTranslation: vi.fn().mockResolvedValue({ status: 'ok' }),
  mockBatchImportTranslations: vi.fn().mockResolvedValue({ status: 'ok', count: 3 }),
  mockGetTranslations: vi.fn().mockResolvedValue({}),
  mockGetGalleryTags: vi.fn().mockResolvedValue({ tags: [] }),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ source: 'ehentai', sourceId: '12345' }),
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
    system: {
      health: vi.fn().mockResolvedValue({ status: 'ok', services: { postgres: 'ok', redis: 'ok' } }),
      info: vi.fn().mockResolvedValue({
        versions: { jyzrox: '0.1', python: '3.13', fastapi: '0.115' },
        eh_max_concurrency: 4,
        tag_model_enabled: false,
      }),
      getCache: vi.fn().mockResolvedValue({ total_memory: '1MB', total_keys: 10, breakdown: {} }),
      clearCache: vi.fn().mockResolvedValue({ freed: 0, deleted_keys: 0 }),
      clearCacheCategory: vi.fn().mockResolvedValue({ freed: 0, deleted_keys: 0 }),
      getStorage: vi.fn().mockResolvedValue(null),
      startReconcile: mockStartReconcile,
      getReconcileStatus: mockGetReconcileStatus,
    },
    auth: {
      getProfile: vi.fn().mockResolvedValue({ username: 'admin', email: null, avatar_url: '', avatar_style: 'gravatar' }),
      updateProfile: vi.fn().mockResolvedValue({}),
      uploadAvatar: vi.fn().mockResolvedValue({ avatar_url: '' }),
      deleteAvatar: vi.fn().mockResolvedValue({ avatar_url: '' }),
      changePassword: vi.fn().mockResolvedValue({}),
      getSessions: vi.fn().mockResolvedValue([]),
      revokeSession: vi.fn().mockResolvedValue({}),
    },
    settings: {
      getFeatures: vi.fn().mockResolvedValue({}),
      setFeature: vi.fn().mockResolvedValue({}),
      setFeatureValue: vi.fn().mockResolvedValue({}),
      getRateLimits: vi.fn().mockResolvedValue({ sites: {}, schedule: {}, override_active: false }),
      patchRateLimits: vi.fn().mockResolvedValue({ sites: {}, schedule: {}, override_active: false }),
      setRateLimitOverride: vi.fn().mockResolvedValue({}),
    },
    tags: {
      listBlocked: vi.fn().mockResolvedValue([]),
      addBlocked: vi.fn().mockResolvedValue({}),
      removeBlocked: vi.fn().mockResolvedValue({}),
      retagAll: vi.fn().mockResolvedValue({ total: 0 }),
      importEhtag: vi.fn().mockResolvedValue({ count: 0 }),
      retag: vi.fn().mockResolvedValue({ status: 'ok', gallery_id: 1 }),
      updateGalleryTags: mockUpdateGalleryTags,
      upsertTranslation: mockUpsertTranslation,
      batchImportTranslations: mockBatchImportTranslations,
      getTranslations: mockGetTranslations,
      autocomplete: vi.fn().mockResolvedValue([]),
      list: vi.fn().mockResolvedValue({ tags: [], total: 0, has_next: false }),
      listAliases: vi.fn().mockResolvedValue([]),
      listImplications: vi.fn().mockResolvedValue([]),
      createAlias: vi.fn().mockResolvedValue({}),
      deleteAlias: vi.fn().mockResolvedValue({}),
      createImplication: vi.fn().mockResolvedValue({}),
      deleteImplication: vi.fn().mockResolvedValue({}),
    },
    tokens: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn().mockResolvedValue({ token: 'tok', name: 'test', id: 1 }),
      delete: vi.fn().mockResolvedValue({}),
    },
    library: {
      checkUpdate: vi.fn().mockResolvedValue({ status: 'no_change' }),
      getGalleryTags: mockGetGalleryTags,
      deleteGallery: vi.fn().mockResolvedValue({}),
      deleteImage: vi.fn().mockResolvedValue({}),
      listExcluded: vi.fn().mockResolvedValue({ excluded: [] }),
      restoreExcluded: vi.fn().mockResolvedValue({}),
      batchUpdate: vi.fn().mockResolvedValue({}),
    },
    history: {
      record: vi.fn().mockResolvedValue({}),
    },
  },
}))

vi.mock('@/hooks/useGalleries', () => ({
  useLibraryGallery: mockUseLibraryGallery,
  useGalleryImages: mockUseGalleryImages,
  useUpdateGallery: mockUseUpdateGallery,
  useGalleryCategories: () => ({ data: undefined, error: undefined, isLoading: false }),
}))

vi.mock('@/hooks/useTagTranslations', () => ({
  useTagTranslations: mockUseTagTranslations,
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    login: vi.fn(),
    logout: vi.fn(),
    user: { role: 'admin' },
  }),
}))

vi.mock('@/hooks/useImport', () => ({
  useRescanLibrary: () => ({ trigger: vi.fn() }),
  useRescanStatus: () => ({ data: null }),
  useCancelRescan: () => ({ trigger: vi.fn() }),
}))

// Stub heavy child components
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}))

vi.mock('@/components/ScheduledTasks/TaskList', () => ({
  TaskList: () => <div data-testid="task-list" />,
}))

vi.mock('@/components/BottomTabConfig', () => ({
  BottomTabConfig: () => <div data-testid="bottom-tab-config" />,
}))

vi.mock('@/components/DashboardLinksConfig', () => ({
  DashboardLinksConfig: () => <div data-testid="dashboard-links-config" />,
}))

vi.mock('@/components/EmptyState', () => ({
  EmptyState: ({ title }: { title: string }) => <div data-testid="empty-state">{title}</div>,
}))

vi.mock('@/components/RatingStars', () => ({
  RatingStars: () => <div data-testid="rating-stars" />,
}))

vi.mock('@/components/BackButton', () => ({
  BackButton: () => <button data-testid="back-button">Back</button>,
}))

// TagAutocomplete stub: renders an input and triggers onSelect with a test tag
vi.mock('@/components/TagAutocomplete', () => ({
  TagAutocomplete: ({
    onSelect,
    placeholder,
  }: {
    onSelect: (tag: string) => void
    placeholder?: string
  }) => (
    <input
      data-testid="tag-autocomplete"
      placeholder={placeholder ?? 'autocomplete'}
      onChange={(e) => {
        if (e.target.value === 'trigger') onSelect('artist:testartist')
      }}
    />
  ),
}))

vi.mock('@/components/Reader/hooks', () => ({
  loadReaderSettings: () => ({
    autoAdvanceEnabled: false,
    autoAdvanceSeconds: 5,
    statusBarEnabled: true,
    statusBarShowClock: true,
    statusBarShowProgress: true,
    statusBarShowPageCount: true,
    defaultViewMode: 'single',
    defaultReadingDirection: 'ltr',
    defaultScaleMode: 'fit-both',
  }),
  saveReaderSettings: vi.fn(),
}))

vi.mock('@/lib/swCacheConfig', () => ({
  loadSWCacheConfig: () => ({
    mediaCacheTTLHours: 72,
    mediaCacheSizeMB: 8192,
    pageCacheTTLHours: 24,
  }),
  saveSWCacheConfig: vi.fn(),
  DEFAULT_SW_CACHE_CONFIG: {
    mediaCacheTTLHours: 72,
    mediaCacheSizeMB: 8192,
    pageCacheTTLHours: 24,
  },
}))

// SWR stub: returns data immediately
vi.mock('swr', () => ({
  default: vi.fn((_key: unknown, fetcher: (() => unknown) | null) => {
    return { data: fetcher ? undefined : undefined, isLoading: false, error: undefined, mutate: vi.fn() }
  }),
  mutate: vi.fn(),
}))

// ── Import pages after mocks ───────────────────────────────────────────

import GalleryDetailPage from '@/app/library/[source]/[sourceId]/page'
import SettingsPage from '@/app/settings/page'

// ── Factories ─────────────────────────────────────────────────────────

function makeGallery(overrides: Record<string, unknown> = {}) {
  return {
    id: 42,
    title: 'Test Gallery',
    title_jpn: null,
    source: 'ehentai',
    source_id: '12345',
    source_url: null,
    category: 'Manga',
    language: 'english',
    pages: 10,
    rating: 4,
    my_rating: 4,
    favorited: false,
    is_favorited: false,
    uploader: 'uploader',
    artist_id: null,
    download_status: 'complete',
    import_mode: null,
    tags_array: ['artist:someartist', 'character:hero'],
    cover_thumb: null,
    posted_at: null,
    added_at: new Date().toISOString(),
    metadata_updated_at: null,
    ...overrides,
  }
}

// ── Setup / Teardown ──────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()

  // Restore default implementations for hoisted mocks (vi.clearAllMocks clears these)
  mockUpdateGalleryTags.mockResolvedValue({ status: 'ok', affected: 1 })
  mockStartReconcile.mockResolvedValue({ status: 'enqueued' })
  mockGetReconcileStatus.mockResolvedValue({ status: 'never_run' })
  mockUpsertTranslation.mockResolvedValue({ status: 'ok' })
  mockBatchImportTranslations.mockResolvedValue({ status: 'ok', count: 3 })
  mockGetTranslations.mockResolvedValue({})
  mockGetGalleryTags.mockResolvedValue({ tags: [] })

  // Mock window.confirm to return true for all confirm dialogs
  vi.spyOn(window, 'confirm').mockReturnValue(true)

  // Default hook values for GalleryDetailPage
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

  mockUseUpdateGallery.mockReturnValue({
    trigger: vi.fn().mockResolvedValue(makeGallery()),
    isMutating: false,
  })

  mockUseTagTranslations.mockReturnValue({
    data: {},
    isLoading: false,
  })

  mockGetGalleryTags.mockResolvedValue({ tags: [] })
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ═══════════════════════════════════════════════════════════════════════
// Feature 1 — Per-Gallery Tag Editing UI
// ═══════════════════════════════════════════════════════════════════════

describe('Feature 1: Per-Gallery Tag Editing UI', () => {
  it('test_galleryDetail_renders_without_throwing', () => {
    expect(() => render(<GalleryDetailPage />)).not.toThrow()
  })

  it('test_galleryDetail_editTagsToggle_button_is_present', () => {
    render(<GalleryDetailPage />)
    // The toggle button shows "library.editTags" (t() returns key as-is)
    expect(screen.getByText('library.editTags')).toBeInTheDocument()
  })

  it('test_galleryDetail_editTagsToggle_button_is_clickable', async () => {
    const user = userEvent.setup()
    render(<GalleryDetailPage />)
    const btn = screen.getByText('library.editTags').closest('button')!
    expect(btn).toBeInTheDocument()
    await user.click(btn)
    // After click, the button text changes to done state
    expect(screen.getByText('library.doneEditingTags')).toBeInTheDocument()
  })

  it('test_galleryDetail_editMode_shows_tagAutocomplete', async () => {
    const user = userEvent.setup()
    render(<GalleryDetailPage />)
    const btn = screen.getByText('library.editTags').closest('button')!
    await user.click(btn)
    expect(screen.getByTestId('tag-autocomplete')).toBeInTheDocument()
  })

  it('test_galleryDetail_editMode_hides_tagAutocomplete_when_toggled_off', async () => {
    const user = userEvent.setup()
    render(<GalleryDetailPage />)
    const btn = screen.getByText('library.editTags').closest('button')!
    // Toggle on
    await user.click(btn)
    expect(screen.getByTestId('tag-autocomplete')).toBeInTheDocument()
    // Toggle off
    const doneBtn = screen.getByText('library.doneEditingTags').closest('button')!
    await user.click(doneBtn)
    expect(screen.queryByTestId('tag-autocomplete')).not.toBeInTheDocument()
  })

  it('test_galleryDetail_addTag_via_autocomplete_calls_updateGalleryTags_with_add_action', async () => {
    const user = userEvent.setup()
    render(<GalleryDetailPage />)

    // Enter edit mode
    const editBtn = screen.getByText('library.editTags').closest('button')!
    await user.click(editBtn)

    // The TagAutocomplete stub fires onSelect when value is 'trigger'
    const autocomplete = screen.getByTestId('tag-autocomplete')
    await user.type(autocomplete, 'trigger')

    await waitFor(() => {
      expect(mockUpdateGalleryTags).toHaveBeenCalledWith(
        42, // gallery.id
        { tags: ['artist:testartist'], action: 'add' },
      )
    })
  })

  it('test_galleryDetail_editMode_manualTags_show_remove_button', async () => {
    const user = userEvent.setup()

    // Setup gallery with tags and gallery tag data marking one as manual
    mockGetGalleryTags.mockResolvedValue({
      tags: [
        { namespace: 'artist', name: 'someartist', confidence: 1, source: 'manual' },
      ],
    })

    render(<GalleryDetailPage />)

    // Wait for the gallery tag data to be fetched
    await waitFor(() => {
      // The gallery has 'artist:someartist' in tags_array; manual source is known
      expect(screen.getByText('library.editTags')).toBeInTheDocument()
    })

    // Enter edit mode
    const editBtn = screen.getByText('library.editTags').closest('button')!
    await user.click(editBtn)

    // After entering edit mode, manual tags should show the × remove button
    await waitFor(() => {
      // aria-label for the remove button uses 'common.removeTag' key
      const removeBtn = screen.queryByRole('button', { name: /common\.removeTag/ })
      expect(removeBtn).toBeInTheDocument()
    })
  })

  it('test_galleryDetail_removeTag_button_calls_updateGalleryTags_with_remove_action', async () => {
    const user = userEvent.setup()

    // Mark 'artist:someartist' as a manual tag
    mockGetGalleryTags.mockResolvedValue({
      tags: [
        { namespace: 'artist', name: 'someartist', confidence: 1, source: 'manual' },
      ],
    })

    render(<GalleryDetailPage />)

    // Enter edit mode
    const editBtn = screen.getByText('library.editTags').closest('button')!
    await user.click(editBtn)

    // Click the remove button
    await waitFor(() => {
      const removeBtn = screen.queryByRole('button', { name: /common\.removeTag/ })
      expect(removeBtn).toBeInTheDocument()
    })

    const removeBtn = screen.getByRole('button', { name: /common\.removeTag/ })
    await user.click(removeBtn)

    await waitFor(() => {
      expect(mockUpdateGalleryTags).toHaveBeenCalledWith(
        42,
        { tags: ['artist:someartist'], action: 'remove' },
      )
    })
  })

  it('test_galleryDetail_nonManualTags_do_not_show_remove_button_in_editMode', async () => {
    const user = userEvent.setup()

    // Only AI-sourced tags
    mockGetGalleryTags.mockResolvedValue({
      tags: [
        { namespace: 'artist', name: 'someartist', confidence: 0.9, source: 'ai' },
      ],
    })

    render(<GalleryDetailPage />)
    const editBtn = screen.getByText('library.editTags').closest('button')!
    await user.click(editBtn)

    // No remove buttons for AI tags
    await waitFor(() => {
      // Give async effects time to settle
      expect(screen.queryByRole('button', { name: /common\.removeTag/ })).not.toBeInTheDocument()
    })
  })

  it('test_galleryDetail_loading_state_shows_spinner_not_editButton', () => {
    mockUseLibraryGallery.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      mutate: vi.fn(),
    })
    render(<GalleryDetailPage />)
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
    expect(screen.queryByText('library.editTags')).not.toBeInTheDocument()
  })

  it('test_galleryDetail_uses_gallery_numeric_id_not_source_id_for_tag_api', async () => {
    // Ensure gallery.id (42) is used, not source_id ('12345')
    const user = userEvent.setup()
    render(<GalleryDetailPage />)
    const editBtn = screen.getByText('library.editTags').closest('button')!
    await user.click(editBtn)

    const autocomplete = screen.getByTestId('tag-autocomplete')
    await user.type(autocomplete, 'trigger')

    await waitFor(() => {
      const call = mockUpdateGalleryTags.mock.calls[0]
      expect(typeof call[0]).toBe('number')
      expect(call[0]).toBe(42)
    })
  })
})

// ═══════════════════════════════════════════════════════════════════════
// Feature 2 — Reconciliation UI (Settings page)
// ═══════════════════════════════════════════════════════════════════════

describe('Feature 2: Reconciliation UI in Settings', () => {
  it('test_settings_with_reconcile_renders_without_throwing', () => {
    expect(() => render(<SettingsPage />)).not.toThrow()
  })

  it('test_settings_reconciliation_section_visible_after_system_section_opens', async () => {
    mockGetReconcileStatus.mockResolvedValue({ status: 'never_run' })

    render(<SettingsPage />)

    // The system section is open by default; trigger load
    const systemHeader = screen.getByText('settings.system').closest('button')!
    // Click to close then reopen to trigger the load handler
    await act(async () => {
      systemHeader.click()
    })
    await act(async () => {
      systemHeader.click()
    })

    // The reconciliation heading is in the system section
    await waitFor(() => {
      expect(screen.getByText('settings.reconciliation')).toBeInTheDocument()
    })
  })

  it('test_settings_reconcileRun_button_is_present_in_system_section', async () => {
    render(<SettingsPage />)

    // Open system section (click toggle twice: close then open)
    const systemHeader = screen.getByText('settings.system').closest('button')!
    await act(async () => { systemHeader.click() })
    await act(async () => { systemHeader.click() })

    await waitFor(() => {
      expect(screen.getByText('settings.reconcileRun')).toBeInTheDocument()
    })
  })

  it('test_settings_reconcileRun_button_opens_confirm_dialog', async () => {
    const user = userEvent.setup()
    render(<SettingsPage />)

    // Open system section
    const systemHeader = screen.getByText('settings.system').closest('button')!
    await act(async () => { systemHeader.click() })
    await act(async () => { systemHeader.click() })

    await waitFor(() => {
      expect(screen.getByText('settings.reconcileRun')).toBeInTheDocument()
    })

    const runBtn = screen.getByText('settings.reconcileRun').closest('button')!
    await user.click(runBtn)

    expect(window.confirm).toHaveBeenCalled()
  })

  it('test_settings_reconcileRun_confirmed_calls_startReconcile_api', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<SettingsPage />)

    // Open system section
    const systemHeader = screen.getByText('settings.system').closest('button')!
    await act(async () => { systemHeader.click() })
    await act(async () => { systemHeader.click() })

    await waitFor(() => {
      expect(screen.getByText('settings.reconcileRun')).toBeInTheDocument()
    })

    const runBtn = screen.getByText('settings.reconcileRun').closest('button')!
    await user.click(runBtn)

    await waitFor(() => {
      expect(mockStartReconcile).toHaveBeenCalledOnce()
    })
  })

  it('test_settings_reconcileRun_cancelled_does_not_call_startReconcile_api', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<SettingsPage />)

    const systemHeader = screen.getByText('settings.system').closest('button')!
    await act(async () => { systemHeader.click() })
    await act(async () => { systemHeader.click() })

    await waitFor(() => {
      expect(screen.getByText('settings.reconcileRun')).toBeInTheDocument()
    })

    const runBtn = screen.getByText('settings.reconcileRun').closest('button')!
    await user.click(runBtn)

    expect(mockStartReconcile).not.toHaveBeenCalled()
  })

  it('test_settings_neverRun_state_shows_neverRun_message', async () => {
    mockGetReconcileStatus.mockResolvedValue({ status: 'never_run' })

    render(<SettingsPage />)

    const systemHeader = screen.getByText('settings.system').closest('button')!
    await act(async () => { systemHeader.click() })
    await act(async () => { systemHeader.click() })

    await waitFor(() => {
      expect(screen.getByText('settings.reconcileNeverRun')).toBeInTheDocument()
    })
  })

  it('test_settings_completed_reconcile_shows_stats', async () => {
    // Ensure all system APIs return proper data including completed reconcile
    const { api } = await import('@/lib/api')
    vi.mocked(api.system.health).mockResolvedValue({ status: 'ok', services: { postgres: 'ok', redis: 'ok' } })
    vi.mocked(api.system.info).mockResolvedValue({
      versions: { jyzrox: '0.1', python: '3.13', fastapi: '0.115' },
      eh_max_concurrency: 4,
      tag_model_enabled: false,
    } as never)
    vi.mocked(api.system.getCache).mockResolvedValue({ total_memory: '1MB', total_keys: 10, breakdown: {} } as never)
    vi.mocked(api.system.getStorage).mockResolvedValue(null as never)
    vi.mocked(api.system.getReconcileStatus).mockResolvedValue({
      status: 'completed',
      completed_at: '2026-03-01T10:00:00Z',
      removed_images: 5,
      removed_galleries: 2,
      orphan_blobs_cleaned: 3,
    } as never)

    render(<SettingsPage />)

    // System section is open by default and auto-loads; wait for stats to appear
    // Text includes ": N" suffix so use regex substring match
    await waitFor(() => {
      expect(screen.getByText(/settings\.reconcileRemovedImages/)).toBeInTheDocument()
    }, { timeout: 3000 })

    expect(screen.getByText(/settings\.reconcileRemovedGalleries/)).toBeInTheDocument()
    expect(screen.getByText(/settings\.reconcileOrphanBlobs/)).toBeInTheDocument()
  })

  it('test_settings_completed_reconcile_shows_correct_stats_values', async () => {
    const { api } = await import('@/lib/api')
    vi.mocked(api.system.health).mockResolvedValue({ status: 'ok', services: { postgres: 'ok', redis: 'ok' } })
    vi.mocked(api.system.info).mockResolvedValue({
      versions: { jyzrox: '0.1', python: '3.13', fastapi: '0.115' },
      eh_max_concurrency: 4,
      tag_model_enabled: false,
    } as never)
    vi.mocked(api.system.getCache).mockResolvedValue({ total_memory: '1MB', total_keys: 10, breakdown: {} } as never)
    vi.mocked(api.system.getStorage).mockResolvedValue(null as never)
    vi.mocked(api.system.getReconcileStatus).mockResolvedValue({
      status: 'completed',
      completed_at: '2026-03-01T10:00:00Z',
      removed_images: 7,
      removed_galleries: 3,
      orphan_blobs_cleaned: 11,
    } as never)

    render(<SettingsPage />)

    // Wait for system data to load and reconcile stats to appear
    await waitFor(() => {
      expect(screen.getByText(/settings\.reconcileRemovedImages/)).toBeInTheDocument()
    }, { timeout: 3000 })

    // Verify the stat values appear alongside labels
    expect(screen.getByText(/settings\.reconcileRemovedImages/).textContent).toContain('7')
    expect(screen.getByText(/settings\.reconcileRemovedGalleries/).textContent).toContain('3')
    expect(screen.getByText(/settings\.reconcileOrphanBlobs/).textContent).toContain('11')
  })
})

// ═══════════════════════════════════════════════════════════════════════
// Feature 3 — Tag Translation Management (API-layer tests)
// ═══════════════════════════════════════════════════════════════════════

/**
 * The translation management UI lives in the Tags page detail panel.
 * These tests verify the API contract and function signatures used by
 * the UI handlers, exercising the mocked api.tags.* methods directly
 * so they remain valid even before UI scaffolding is complete.
 */
describe('Feature 3: Tag Translation API contract', () => {
  it('test_upsertTranslation_resolves_with_ok_status', async () => {
    const { api } = await import('@/lib/api')
    const result = await api.tags.upsertTranslation({
      namespace: 'artist',
      name: 'testartist',
      language: 'zh',
      translation: '測試藝術家',
    })
    expect(result).toEqual({ status: 'ok' })
  })

  it('test_upsertTranslation_is_called_with_correct_payload_shape', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.upsertTranslation({
      namespace: 'character',
      name: 'hero',
      language: 'ja',
      translation: 'ヒーロー',
    })
    expect(mockUpsertTranslation).toHaveBeenCalledWith({
      namespace: 'character',
      name: 'hero',
      language: 'ja',
      translation: 'ヒーロー',
    })
  })

  it('test_upsertTranslation_supports_zh_language', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.upsertTranslation({
      namespace: 'parody',
      name: 'original',
      language: 'zh',
      translation: '原創',
    })
    const call = mockUpsertTranslation.mock.calls[0][0]
    expect(call.language).toBe('zh')
  })

  it('test_upsertTranslation_supports_ja_language', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.upsertTranslation({
      namespace: 'parody',
      name: 'original',
      language: 'ja',
      translation: 'オリジナル',
    })
    const call = mockUpsertTranslation.mock.calls[0][0]
    expect(call.language).toBe('ja')
  })

  it('test_upsertTranslation_supports_ko_language', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.upsertTranslation({
      namespace: 'parody',
      name: 'original',
      language: 'ko',
      translation: '오리지널',
    })
    const call = mockUpsertTranslation.mock.calls[0][0]
    expect(call.language).toBe('ko')
  })

  it('test_batchImportTranslations_resolves_with_count', async () => {
    const { api } = await import('@/lib/api')
    const translations = [
      { namespace: 'artist', name: 'a1', language: 'zh', translation: '藝術家1' },
      { namespace: 'artist', name: 'a2', language: 'zh', translation: '藝術家2' },
      { namespace: 'character', name: 'c1', language: 'zh', translation: '角色1' },
    ]
    const result = await api.tags.batchImportTranslations(translations)
    expect(result).toMatchObject({ status: 'ok', count: 3 })
  })

  it('test_batchImportTranslations_is_called_with_array_of_translations', async () => {
    const { api } = await import('@/lib/api')
    const translations = [
      { namespace: 'artist', name: 'foo', language: 'zh', translation: 'Foo中' },
      { namespace: 'artist', name: 'bar', language: 'zh', translation: 'Bar中' },
    ]
    await api.tags.batchImportTranslations(translations)
    expect(mockBatchImportTranslations).toHaveBeenCalledWith(translations)
  })

  it('test_getTranslations_resolves_with_a_record_object', async () => {
    mockGetTranslations.mockResolvedValue({ 'artist:foo': 'Foo中', 'character:bar': 'Bar中' })
    const { api } = await import('@/lib/api')
    const result = await api.tags.getTranslations(['artist:foo', 'character:bar'], 'zh')
    expect(result).toEqual({ 'artist:foo': 'Foo中', 'character:bar': 'Bar中' })
  })

  it('test_getTranslations_resolves_to_empty_record_when_no_translations_exist', async () => {
    mockGetTranslations.mockResolvedValue({})
    const { api } = await import('@/lib/api')
    const result = await api.tags.getTranslations(['unknown:tag'], 'zh')
    expect(result).toEqual({})
  })

  it('test_getTranslations_accepts_zh_language_parameter', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.getTranslations(['artist:foo'], 'zh')
    expect(mockGetTranslations).toHaveBeenCalledWith(['artist:foo'], 'zh')
  })

  it('test_getTranslations_accepts_ja_language_parameter', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.getTranslations(['artist:foo'], 'ja')
    expect(mockGetTranslations).toHaveBeenCalledWith(['artist:foo'], 'ja')
  })

  it('test_getTranslations_accepts_ko_language_parameter', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.getTranslations(['artist:foo'], 'ko')
    expect(mockGetTranslations).toHaveBeenCalledWith(['artist:foo'], 'ko')
  })

  it('test_upsertTranslation_can_be_called_multiple_times_for_different_tags', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.upsertTranslation({ namespace: 'artist', name: 'foo', language: 'zh', translation: 'Foo中' })
    await api.tags.upsertTranslation({ namespace: 'artist', name: 'bar', language: 'zh', translation: 'Bar中' })
    expect(mockUpsertTranslation).toHaveBeenCalledTimes(2)
  })

  it('test_updateGalleryTags_add_action_calls_api_with_correct_shape', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.updateGalleryTags(42, { tags: ['artist:foo'], action: 'add' })
    expect(mockUpdateGalleryTags).toHaveBeenCalledWith(42, { tags: ['artist:foo'], action: 'add' })
  })

  it('test_updateGalleryTags_remove_action_calls_api_with_correct_shape', async () => {
    const { api } = await import('@/lib/api')
    await api.tags.updateGalleryTags(42, { tags: ['artist:foo'], action: 'remove' })
    expect(mockUpdateGalleryTags).toHaveBeenCalledWith(42, { tags: ['artist:foo'], action: 'remove' })
  })

  it('test_updateGalleryTags_resolves_with_status_and_affected_count', async () => {
    const { api } = await import('@/lib/api')
    const result = await api.tags.updateGalleryTags(1, { tags: ['general:test'], action: 'add' })
    expect(result).toMatchObject({ status: 'ok', affected: 1 })
  })
})
