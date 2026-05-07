import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'

const mockDismissAlert = vi.fn()
const mockMutateAlerts = vi.fn()

vi.mock('swr', () => ({
  default: vi.fn((key: string) => {
    if (key === 'dashboard/alerts') {
      return {
        data: {
          alerts: [
            'ExHentai access denied (Sad Panda)',
            'ExHentai access denied (Sad Panda)',
          ],
        },
        mutate: mockMutateAlerts,
      }
    }
    if (key === 'dashboard/jobs') {
      return { data: { jobs: [] } }
    }
    return { data: { galleries: [], total: 0 }, isLoading: false }
  }),
}))

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string
    children: ReactNode
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/api', () => ({
  api: {
    settings: {
      dismissAlert: mockDismissAlert,
    },
    library: {
      getGalleries: vi.fn(),
    },
    download: {
      getJobs: vi.fn(),
    },
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

describe('Dashboard alerts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDismissAlert.mockResolvedValue({ status: 'ok', dismissed: 2 })
    mockMutateAlerts.mockResolvedValue(undefined)
    sessionStorage.clear()
    localStorage.clear()
  })

  it('deduplicates visible alerts and dismisses the backend alert queue', async () => {
    const { default: Dashboard } = await import('@/app/page')
    render(<Dashboard />)

    const alertMessage = 'ExHentai access denied (Sad Panda)'
    expect(screen.getAllByText(alertMessage)).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'common.dismissAlert' }))

    expect(screen.queryByText(alertMessage)).toBeNull()
    await waitFor(() => {
      expect(mockDismissAlert).toHaveBeenCalledWith(alertMessage)
    })
    expect(mockMutateAlerts).toHaveBeenCalledWith(expect.any(Function), { revalidate: false })
  })
})
