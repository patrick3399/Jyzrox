/**
 * DownloadDashboardPage — Vitest test suite
 *
 * Covers:
 *   Page renders without errors for admin users
 *   Page renders the dashboard title
 *   Page renders the Running, Queued, Today global stat chips
 *   Page renders active jobs section heading
 *   Page renders queued jobs section heading
 *   Page redirects non-admin users to '/'
 *   Loading state renders a spinner, not the title
 *   No active jobs shows the empty state message
 *   No queued jobs shows the empty state message
 *
 * Mock strategy:
 *   - next/navigation → stub useRouter (capture replace calls) and useSearchParams
 *   - @/hooks/useProfile → controlled per test via hoisted mock
 *   - @/hooks/useDashboard → controlled per test via hoisted mock
 *   - @/lib/ws → stub returning idle WS state (required by useDashboard internally)
 *   - @/lib/api → stub download and settings calls used by action handlers
 *   - @/lib/i18n → t() returns key as-is for predictable assertions
 *   - @/components/LocaleProvider → stub useLocale
 *   - sonner → stub toast
 *   - lucide-react → not mocked (pure SVG, no side effects)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const { mockRouterReplace, mockUseProfile, mockUseDashboard } = vi.hoisted(() => ({
  mockRouterReplace: vi.fn(),
  mockUseProfile: vi.fn(),
  mockUseDashboard: vi.fn(),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: mockRouterReplace }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, _params?: Record<string, unknown>) => key,
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'en', setLocale: vi.fn() }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/api', () => ({
  api: {
    download: {
      pauseJob: vi.fn().mockResolvedValue({}),
      resumeJob: vi.fn().mockResolvedValue({}),
      cancelJob: vi.fn().mockResolvedValue({}),
      getDashboard: vi.fn().mockResolvedValue(null),
    },
    settings: {
      setRateLimitOverride: vi.fn().mockResolvedValue({}),
    },
  },
}))

// useDashboard uses useWs internally — stub it to return idle state.
vi.mock('@/lib/ws', () => ({
  useWs: () => ({
    connected: false,
    lastJobUpdate: null,
    lastEvent: null,
  }),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: mockUseProfile,
}))

vi.mock('@/hooks/useDashboard', () => ({
  useDashboard: mockUseDashboard,
}))

// ── Import page AFTER mocks ────────────────────────────────────────────

import DownloadDashboardPage from '@/app/admin/dashboard/page'

// ── Factories ─────────────────────────────────────────────────────────

function makeJob(id: string, status: string = 'running') {
  return {
    id,
    url: `https://e-hentai.org/g/${id}/abc/`,
    source: 'ehentai',
    status,
    progress: { percent: 50, downloaded: 5, total: 10, speed: 1.5 },
    error: null,
    created_at: new Date().toISOString(),
    finished_at: null,
    retry_count: 0,
    max_retries: 3,
    next_retry_at: null,
    gallery_id: null,
    subscription_id: null,
  }
}

function makeDashboardData(overrides: Record<string, unknown> = {}) {
  return {
    active_jobs: [],
    queued_jobs: [],
    site_stats: {},
    global: {
      boost_mode: false,
      total_running: 0,
      total_queued: 0,
      total_today: 0,
    },
    system: {
      disk_free_gb: 42.0,
      disk_ok: true,
    },
    ...overrides,
  }
}

// ── State helpers ──────────────────────────────────────────────────────

function setAdminProfile() {
  mockUseProfile.mockReturnValue({
    data: { role: 'admin', username: 'admin', email: null },
    isLoading: false,
    error: null,
  })
}

function setProfileLoading() {
  mockUseProfile.mockReturnValue({
    data: undefined,
    isLoading: true,
    error: null,
  })
}

function setNonAdminProfile(role: string) {
  mockUseProfile.mockReturnValue({
    data: { role, username: 'user', email: null },
    isLoading: false,
    error: null,
  })
}

function setDashboardData(data: ReturnType<typeof makeDashboardData> | null) {
  mockUseDashboard.mockReturnValue({
    data,
    isLoading: false,
    error: null,
    mutate: vi.fn(),
  })
}

function setDashboardLoading() {
  mockUseDashboard.mockReturnValue({
    data: undefined,
    isLoading: true,
    error: null,
    mutate: vi.fn(),
  })
}

// ── Setup / Teardown ──────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  setAdminProfile()
  setDashboardData(makeDashboardData())
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('DownloadDashboardPage — render without errors', () => {
  it('test_dashboard_page_renders_without_errors', async () => {
    await act(async () => {
      expect(() => render(<DownloadDashboardPage />)).not.toThrow()
    })
  })

  it('test_dashboard_page_renders_title', async () => {
    await act(async () => {
      render(<DownloadDashboardPage />)
    })
    expect(screen.getByText('downloadDashboard.title')).toBeInTheDocument()
  })

  it('test_dashboard_page_renders_running_stat_label', async () => {
    await act(async () => {
      render(<DownloadDashboardPage />)
    })
    expect(screen.getByText('downloadDashboard.running')).toBeInTheDocument()
  })

  it('test_dashboard_page_renders_queued_stat_label', async () => {
    await act(async () => {
      render(<DownloadDashboardPage />)
    })
    expect(screen.getByText('downloadDashboard.queued')).toBeInTheDocument()
  })

  it('test_dashboard_page_renders_today_stat_label', async () => {
    await act(async () => {
      render(<DownloadDashboardPage />)
    })
    expect(screen.getByText('downloadDashboard.today')).toBeInTheDocument()
  })

  it('test_dashboard_page_renders_active_jobs_section_heading', async () => {
    await act(async () => {
      render(<DownloadDashboardPage />)
    })
    expect(screen.getByText('downloadDashboard.activeJobs')).toBeInTheDocument()
  })

  it('test_dashboard_page_renders_queued_jobs_section_heading', async () => {
    await act(async () => {
      render(<DownloadDashboardPage />)
    })
    expect(screen.getByText('downloadDashboard.queuedJobs')).toBeInTheDocument()
  })
})

describe('DownloadDashboardPage — access control', () => {
  it('test_dashboard_page_redirects_viewer_to_home', async () => {
    setNonAdminProfile('viewer')
    setDashboardData(makeDashboardData())

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(mockRouterReplace).toHaveBeenCalledWith('/')
  })

  it('test_dashboard_page_redirects_member_to_home', async () => {
    setNonAdminProfile('member')
    setDashboardData(makeDashboardData())

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(mockRouterReplace).toHaveBeenCalledWith('/')
  })

  it('test_dashboard_page_does_not_redirect_admin', async () => {
    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(mockRouterReplace).not.toHaveBeenCalledWith('/')
  })
})

describe('DownloadDashboardPage — loading state', () => {
  it('test_dashboard_page_shows_spinner_when_dashboard_loading', async () => {
    setDashboardLoading()

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    // Title should NOT be visible while loading
    expect(screen.queryByText('downloadDashboard.title')).not.toBeInTheDocument()
  })

  it('test_dashboard_page_shows_spinner_when_profile_loading', async () => {
    setProfileLoading()
    setDashboardData(null)

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    // Title should NOT be visible while profile is still loading
    expect(screen.queryByText('downloadDashboard.title')).not.toBeInTheDocument()
  })
})

describe('DownloadDashboardPage — empty states', () => {
  it('test_dashboard_page_no_active_jobs_shows_empty_message', async () => {
    setDashboardData(makeDashboardData({ active_jobs: [] }))

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(screen.getByText('downloadDashboard.noActiveJobs')).toBeInTheDocument()
  })

  it('test_dashboard_page_no_queued_jobs_shows_empty_message', async () => {
    setDashboardData(makeDashboardData({ queued_jobs: [] }))

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(screen.getByText('downloadDashboard.noQueuedJobs')).toBeInTheDocument()
  })

  it('test_dashboard_page_null_data_shows_failed_to_load', async () => {
    setDashboardData(null)

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(screen.getByText('common.failedToLoad')).toBeInTheDocument()
  })
})

describe('DownloadDashboardPage — active jobs', () => {
  it('test_dashboard_page_active_jobs_renders_job_source', async () => {
    const job = makeJob('job-123', 'running')
    setDashboardData(
      makeDashboardData({
        active_jobs: [job],
        global: { boost_mode: false, total_running: 1, total_queued: 0, total_today: 1 },
      }),
    )

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    // The ActiveJobCard renders job.source as a muted sub-line
    expect(screen.getByText('ehentai')).toBeInTheDocument()
  })

  it('test_dashboard_page_active_jobs_no_empty_message_when_jobs_present', async () => {
    const job = makeJob('job-456', 'running')
    setDashboardData(
      makeDashboardData({
        active_jobs: [job],
        global: { boost_mode: false, total_running: 1, total_queued: 0, total_today: 1 },
      }),
    )

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(screen.queryByText('downloadDashboard.noActiveJobs')).not.toBeInTheDocument()
  })
})

describe('DownloadDashboardPage — boost mode display', () => {
  it('test_dashboard_page_boost_mode_button_is_present', async () => {
    setDashboardData(makeDashboardData())

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    expect(screen.getByText('downloadDashboard.boostMode')).toBeInTheDocument()
  })

  it('test_dashboard_page_global_counts_displayed', async () => {
    setDashboardData(
      makeDashboardData({
        global: {
          boost_mode: false,
          total_running: 3,
          total_queued: 7,
          total_today: 15,
        },
      }),
    )

    await act(async () => {
      render(<DownloadDashboardPage />)
    })

    // Numbers are rendered as plain text inside stat chips
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
  })
})
