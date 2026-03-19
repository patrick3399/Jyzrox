/**
 * Settings page — Worker Recovery section
 *
 * Covers:
 *   Recovery section renders with two select dropdowns after opening it
 *   Changing running strategy dropdown calls patchRecoveryStrategy API
 *   Changing paused strategy dropdown calls patchRecoveryStrategy API
 *
 * Mock strategy:
 *   - All API calls mocked (same as pages/settings.test.tsx)
 *   - getRecoveryStrategy returns { running: 'auto_retry', paused: 'keep_paused' }
 *   - patchRecoveryStrategy returns updated values
 *   - t() returns the key as-is for predictable assertions
 *   - useAuth → admin user so the workerRecovery section is accessible
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── Module mocks ────────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
  SUPPORTED_LOCALES: ['en'],
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'en', setLocale: vi.fn() }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const { mockPatchRecoveryStrategy, mockGetRecoveryStrategy } = vi.hoisted(() => ({
  mockPatchRecoveryStrategy: vi.fn(),
  mockGetRecoveryStrategy: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  api: {
    system: {
      health: vi.fn().mockResolvedValue({ status: 'ok', services: {} }),
      info: vi.fn().mockResolvedValue({ versions: {} }),
      getCache: vi.fn().mockResolvedValue({ total_size: 0, total_keys: 0, breakdown: {} }),
      clearCache: vi.fn().mockResolvedValue({ freed: 0 }),
      clearCacheCategory: vi.fn().mockResolvedValue({ freed: 0 }),
    },
    auth: {
      getProfile: vi.fn().mockResolvedValue({ email: null, avatar_url: null }),
      updateProfile: vi.fn().mockResolvedValue({}),
      uploadAvatar: vi.fn().mockResolvedValue({ avatar_url: null }),
      deleteAvatar: vi.fn().mockResolvedValue({}),
      changePassword: vi.fn().mockResolvedValue({}),
      getSessions: vi.fn().mockResolvedValue([]),
      revokeSession: vi.fn().mockResolvedValue({}),
    },
    settings: {
      getFeatures: vi.fn().mockResolvedValue({}),
      setFeature: vi.fn().mockResolvedValue({}),
      setFeatureValue: vi.fn().mockResolvedValue({}),
      getRateLimits: vi.fn().mockResolvedValue({ sites: {}, schedule: {}, override_active: false }),
      patchRateLimits: vi
        .fn()
        .mockResolvedValue({ sites: {}, schedule: {}, override_active: false }),
      setRateLimitOverride: vi.fn().mockResolvedValue({}),
      getRecoveryStrategy: mockGetRecoveryStrategy,
      patchRecoveryStrategy: mockPatchRecoveryStrategy,
    },
    tags: {
      listBlocked: vi.fn().mockResolvedValue([]),
      addBlocked: vi.fn().mockResolvedValue({}),
      removeBlocked: vi.fn().mockResolvedValue({}),
      retagAll: vi.fn().mockResolvedValue({ total: 0 }),
      importEhtag: vi.fn().mockResolvedValue({ count: 0 }),
    },
    tokens: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn().mockResolvedValue({ token: 'tok', name: 'test', id: 1 }),
      delete: vi.fn().mockResolvedValue({}),
    },
  },
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

// ── Import page AFTER mocks ─────────────────────────────────────────────

import SettingsPage from '@/app/settings/page'

// ── Setup / Teardown ───────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockGetRecoveryStrategy.mockResolvedValue({ running: 'auto_retry', paused: 'keep_paused' })
  mockPatchRecoveryStrategy.mockResolvedValue({ running: 'mark_failed', paused: 'keep_paused' })
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Helper: open the Worker Recovery section ───────────────────────────

async function openRecoverySection(user: ReturnType<typeof userEvent.setup>) {
  render(<SettingsPage />)
  const header = screen.getByText('settings.workerRecovery').closest('button')!
  await user.click(header)
  // Wait for the section contents to appear
  await waitFor(() => {
    expect(screen.getByText('settings.recoveryRunning')).toBeInTheDocument()
  })
}

// ── Tests ───────────────────────────────────────────────────────────────

describe('Settings page — Worker Recovery section', () => {
  it('test_recovery_section_renders_two_select_dropdowns', async () => {
    const user = userEvent.setup()
    await openRecoverySection(user)

    // Both row labels must be visible
    expect(screen.getByText('settings.recoveryRunning')).toBeInTheDocument()
    expect(screen.getByText('settings.recoveryPaused')).toBeInTheDocument()

    // Two <select> elements must be present inside the section
    const selects = screen.getAllByRole('combobox')
    expect(selects.length).toBeGreaterThanOrEqual(2)
  })

  it('test_recovery_section_selects_have_correct_options', async () => {
    const user = userEvent.setup()
    await openRecoverySection(user)

    // auto_retry appears in both selects
    expect(screen.getAllByText('settings.recoveryAutoRetry').length).toBeGreaterThanOrEqual(2)
    // mark_failed appears in both selects
    expect(screen.getAllByText('settings.recoveryMarkFailed').length).toBeGreaterThanOrEqual(2)
    // keep_paused only in the paused select
    expect(screen.getAllByText('settings.recoveryKeepPaused').length).toBeGreaterThanOrEqual(1)
  })

  it('test_recovery_section_changing_running_strategy_calls_api', async () => {
    const user = userEvent.setup()
    await openRecoverySection(user)

    await waitFor(() => {
      expect(mockGetRecoveryStrategy).toHaveBeenCalledTimes(1)
    })

    // Find the running select by looking for the select element near the
    // "settings.recoveryRunning" label text.
    const runningLabel = screen.getByText('settings.recoveryRunning')
    const runningRow = runningLabel.closest('.flex.items-center')!
    const runningSelect = runningRow.querySelector('select')!

    await user.selectOptions(runningSelect, 'mark_failed')

    await waitFor(() => {
      expect(mockPatchRecoveryStrategy).toHaveBeenCalledWith({ running: 'mark_failed' })
    })
  })

  it('test_recovery_section_changing_paused_strategy_calls_api', async () => {
    const user = userEvent.setup()
    mockPatchRecoveryStrategy.mockResolvedValue({ running: 'auto_retry', paused: 'auto_retry' })

    await openRecoverySection(user)

    await waitFor(() => {
      expect(mockGetRecoveryStrategy).toHaveBeenCalledTimes(1)
    })

    const pausedLabel = screen.getByText('settings.recoveryPaused')
    const pausedRow = pausedLabel.closest('.flex.items-center')!
    const pausedSelect = pausedRow.querySelector('select')!

    await user.selectOptions(pausedSelect, 'auto_retry')

    await waitFor(() => {
      expect(mockPatchRecoveryStrategy).toHaveBeenCalledWith({ paused: 'auto_retry' })
    })
  })
})
