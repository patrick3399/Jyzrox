import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const mockUpdateTask = vi.fn()
const mockRunTask = vi.fn()
const mockMutate = vi.fn()
let mockTasksData: unknown = undefined

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('@/lib/timeUtils', () => ({
  timeAgo: (value: string | null) => (value ? '1 hour ago' : ''),
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/hooks/useScheduledTasks', () => ({
  useScheduledTasks: () => ({
    data: mockTasksData,
    isLoading: false,
    mutate: mockMutate,
  }),
  useUpdateTask: () => ({
    trigger: mockUpdateTask,
  }),
  useRunTask: () => ({
    trigger: mockRunTask,
  }),
}))

import { TaskList } from '@/components/ScheduledTasks/TaskList'
import type { ScheduledTask } from '@/lib/types'

function task(overrides: Partial<ScheduledTask>): ScheduledTask {
  return {
    id: 'reconciliation',
    name: 'Reconciliation',
    description: 'Verify consistency',
    enabled: true,
    cron_expr: '0 3 * * 1',
    default_cron: '0 3 * * 1',
    next_run: '2030-01-01T00:00:00+00:00',
    last_run: '2026-04-28T12:00:00+00:00',
    last_status: 'ok',
    last_error: null,
    ...overrides,
  }
}

describe('ScheduledTasks components', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUpdateTask.mockResolvedValue({ status: 'ok' })
    mockRunTask.mockResolvedValue({ status: 'queued' })
    mockTasksData = {
      tasks: [
        task({
          id: 'reconciliation',
          name: 'Reconciliation',
        }),
        task({
          id: 'library_scan',
          name: 'External Folder Scan',
          description: 'Scan external folders and update linked local galleries',
          cron_expr: '0 * * * *',
          default_cron: '0 * * * *',
        }),
      ],
    }
  })

  it('pins library_scan as the external folder scan section', () => {
    render(<TaskList />)

    const pinned = screen.getByText('scheduledTasks.externalFolderScan').closest('section')
    expect(pinned).not.toBeNull()
    expect(within(pinned!).getByText('External Folder Scan')).toBeDefined()
    expect(screen.getByText('scheduledTasks.otherTasks')).toBeDefined()
  })

  it('shows next run when the pinned task provides one', () => {
    render(<TaskList />)

    const pinned = screen.getByText('scheduledTasks.externalFolderScan').closest('section')
    expect(pinned).not.toBeNull()
    expect(within(pinned!).getByText(/scheduledTasks\.nextRunAgo/)).toBeDefined()
  })

  it('shows disabled next run text when the task is disabled', () => {
    mockTasksData = {
      tasks: [
        task({
          id: 'library_scan',
          name: 'External Folder Scan',
          enabled: false,
          next_run: null,
        }),
      ],
    }

    render(<TaskList />)

    expect(screen.getByText('scheduledTasks.nextRunDisabled')).toBeDefined()
  })

  it('keeps scheduled task controls wired to existing handlers', () => {
    render(<TaskList />)

    const pinned = screen.getByText('scheduledTasks.externalFolderScan').closest('section')
    expect(pinned).not.toBeNull()

    fireEvent.click(within(pinned!).getByRole('button', { name: 'settings.tasks.disableTask' }))
    fireEvent.click(within(pinned!).getByText('settings.tasks.runNow'))

    expect(mockUpdateTask).toHaveBeenCalledWith({
      taskId: 'library_scan',
      data: { enabled: false },
    })
    expect(mockRunTask).toHaveBeenCalledWith('library_scan')
  })
})
