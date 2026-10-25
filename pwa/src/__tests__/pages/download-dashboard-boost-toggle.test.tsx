import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockDashboard = vi.fn()
const mockMutate = vi.fn()
const mockSetOverride = vi.fn()

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
  useDashboard: () => ({ data: mockDashboard(), isLoading: false, mutate: mockMutate }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/lib/api', () => ({
  api: {
    settings: { setRateLimitOverride: (...args: unknown[]) => mockSetOverride(...args) },
    download: { pauseJob: vi.fn(), resumeJob: vi.fn(), cancelJob: vi.fn() },
    system: { getEvents: vi.fn() },
  },
}))

vi.mock('swr', () => ({
  default: () => ({ data: { events: [] } }),
}))

function dashboard(boost: boolean) {
  return {
    global: { boost_mode: boost, total_running: 3, total_queued: 0, total_today: 7 },
    system: { disk_free_gb: 100, disk_ok: true },
    site_stats: {},
    active_jobs: [],
    queued_jobs: [],
  }
}

describe('download dashboard boost toggle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSetOverride.mockResolvedValue(undefined)
    mockMutate.mockResolvedValue(undefined)
  })

  it('shows the new boost state from the click itself instead of waiting for a refetch of a cached snapshot', async () => {
    mockDashboard.mockReturnValue(dashboard(false))
    const { default: Page } = await import('@/app/admin/dashboard/page')

    render(<Page />)
    fireEvent.click(screen.getByText('downloadDashboard.toggleBoostOn').closest('button')!)

    await waitFor(() => expect(mockSetOverride).toHaveBeenCalledWith(true))
    await waitFor(() => expect(mockMutate).toHaveBeenCalled())

    const [updater] = mockMutate.mock.calls[0]
    expect(typeof updater).toBe('function')
    const next = updater(dashboard(false))
    expect(next.global.boost_mode).toBe(true)
    expect(next.global.total_running).toBe(3)
  })

  it('turns boost off from the state it just wrote, so a second click is not a repeat of the first', async () => {
    mockDashboard.mockReturnValue(dashboard(true))
    const { default: Page } = await import('@/app/admin/dashboard/page')

    render(<Page />)
    fireEvent.click(screen.getByText('downloadDashboard.toggleBoostOff').closest('button')!)

    await waitFor(() => expect(mockSetOverride).toHaveBeenCalledWith(false))
    await waitFor(() => expect(mockMutate).toHaveBeenCalled())

    const [updater] = mockMutate.mock.calls[0]
    expect(updater(dashboard(true)).global.boost_mode).toBe(false)
  })
})
