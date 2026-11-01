import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockGetJobs = vi.fn()
let jobsData: { total: number; jobs: Array<Record<string, unknown>> } | undefined

vi.mock('swr', () => ({
  default: vi.fn((key: string, fetcher?: () => unknown) => {
    if (key === 'dashboard/jobs') {
      // Exercise the real fetcher so its arguments can be asserted.
      void fetcher?.()
      return { data: jobsData }
    }
    if (key === 'dashboard/alerts') return { data: { alerts: [] }, mutate: vi.fn() }
    return { data: { galleries: [], total: 0 }, isLoading: false }
  }),
}))

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/api', () => ({
  api: {
    settings: { dismissAlert: vi.fn() },
    library: { getGalleries: vi.fn() },
    download: { getJobs: (...args: unknown[]) => mockGetJobs(...args) },
  },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/components/DashboardLinksConfig', () => ({
  DASHBOARD_LINKS_CONFIG_KEY: 'dashboard_links_config',
  loadDashboardConfig: () => [],
}))

vi.mock('@/components/Skeleton', () => ({
  SkeletonGrid: () => <div data-testid="skeleton-grid" />,
}))

vi.mock('@/components/EmptyState', () => ({
  EmptyState: () => <div data-testid="empty-state" />,
}))

const job = (id: string, status: string, subscription_id: number | null) => ({
  id,
  url: `https://example.test/${id}`,
  source: 'ehentai',
  status,
  progress: {},
  error: null,
  created_at: '2026-10-15T14:00:00Z',
  finished_at: null,
  retry_count: 0,
  max_retries: 3,
  subscription_id,
})

async function renderDashboard() {
  const { default: Dashboard } = await import('@/app/page')
  render(<Dashboard />)
}

describe('Dashboard active downloads', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    jobsData = undefined
    sessionStorage.clear()
    localStorage.clear()
  })

  it('fetches only active jobs, limited to 5', async () => {
    jobsData = { total: 0, jobs: [] }
    await renderDashboard()

    expect(mockGetJobs).toHaveBeenCalledWith({ active_only: true, limit: 5 })
  })

  it('shows the server total in the header, not the number of fetched jobs', async () => {
    jobsData = {
      total: 12,
      jobs: [job('a', 'running', 1), job('b', 'paused', 2), job('c', 'queued', null)],
    }
    await renderDashboard()

    expect(screen.getByText('dashboard.activeDownloads (12)')).toBeInTheDocument()
    expect(screen.queryByText('dashboard.activeDownloads (3)')).not.toBeInTheDocument()
  })

  it('shows paused jobs because the server already filtered to active ones', async () => {
    jobsData = { total: 1, jobs: [job('paused-job', 'paused', null)] }
    await renderDashboard()

    expect(screen.getByText('https://example.test/paused-job')).toBeInTheDocument()
  })

  it('links "View all" to the subscription section when every job has a subscription_id', async () => {
    jobsData = { total: 2, jobs: [job('a', 'running', 1), job('b', 'queued', 0)] }
    await renderDashboard()

    expect(screen.getByRole('link', { name: /dashboard\.viewAll/ })).toHaveAttribute(
      'href',
      '/queue#subscription-active',
    )
  })

  it('links "View all" to the plain queue when manual and subscription jobs are mixed', async () => {
    jobsData = { total: 2, jobs: [job('a', 'running', 1), job('b', 'queued', null)] }
    await renderDashboard()

    expect(screen.getByRole('link', { name: /dashboard\.viewAll/ })).toHaveAttribute(
      'href',
      '/queue',
    )
  })
})
