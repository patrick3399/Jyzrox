import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockDashboard = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn() }),
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'en' }),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { role: 'admin' }, isLoading: false }),
}))

vi.mock('@/hooks/useDashboard', () => ({
  useDashboard: () => ({ data: mockDashboard(), isLoading: false, mutate: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/lib/api', () => ({
  api: {
    settings: { setRateLimitOverride: vi.fn() },
    download: { pauseJob: vi.fn(), resumeJob: vi.fn(), cancelJob: vi.fn() },
    system: { getEvents: vi.fn() },
  },
}))

vi.mock('swr', () => ({
  default: () => ({ data: { events: [] } }),
}))

const queuedJob = (id: string, progress: Record<string, unknown>) => ({
  id,
  url: `https://example.test/${id}`,
  source: 'ehentai',
  status: 'queued' as const,
  progress,
  error: null,
  created_at: '2026-08-01T00:00:00Z',
  finished_at: null,
  retry_count: 0,
  max_retries: 3,
})

function dashboardWith(jobs: ReturnType<typeof queuedJob>[]) {
  return {
    global: { boost_mode: false, total_running: 0, total_queued: jobs.length, total_today: 0 },
    system: { disk_free_gb: 100, disk_ok: true },
    site_stats: {
      ehentai: {
        semaphore: { used: 1, max: 1 },
        queued: jobs.length,
        running: 1,
        avg_speed: 0,
        current_delay_ms: 0,
        adaptive: { sleep_multiplier: 1, last_429_at: null },
      },
    },
    active_jobs: [],
    queued_jobs: jobs,
  }
}

describe('download dashboard queued reasons', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders a source-slot reason only when the backend explicitly supplies it', async () => {
    mockDashboard.mockReturnValue(
      dashboardWith([
        queuedJob('waiting', { wait_reason: 'source_slot', semaphore_key: 'ehentai' }),
      ]),
    )
    const { default: Page } = await import('@/app/admin/dashboard/page')

    render(<Page />)

    expect(screen.getByText('downloadDashboard.waitingForSlot')).toBeInTheDocument()
  })

  it('does not guess that a generic queued job is waiting for a source slot', async () => {
    mockDashboard.mockReturnValue(dashboardWith([queuedJob('transport-backlog', {})]))
    const { default: Page } = await import('@/app/admin/dashboard/page')

    render(<Page />)

    expect(screen.queryByText('downloadDashboard.waitingForSlot')).not.toBeInTheDocument()
  })
})
