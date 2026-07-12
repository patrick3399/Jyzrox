import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { TagHealthReport } from '@/lib/types'

// ---------------------------------------------------------------------------
// Shared mock state
// ---------------------------------------------------------------------------

const h = vi.hoisted(() => ({
  report: {
    orphans: [{ id: 1, namespace: 'general', name: 'orphan_tag', count: 0 }],
    orphans_total: 5,
    duplicates: [
      {
        key: 'general:bluehair',
        tags: [
          { id: 2, namespace: 'general', name: 'blue_hair', count: 120 },
          { id: 3, namespace: 'general', name: 'blue-hair', count: 2 },
        ],
      },
    ],
    implication_cycles: [
      {
        key: '10-11',
        path: [
          { id: 10, namespace: 'general', name: 'a' },
          { id: 11, namespace: 'general', name: 'b' },
        ],
      },
    ],
    ignored_count: 1,
  } as TagHealthReport,
  ignored: { keys: ['dup:general:other'] },
  profileRole: 'viewer' as string,
}))

const emptyReport: TagHealthReport = {
  orphans: [],
  orphans_total: 0,
  duplicates: [],
  implication_cycles: [],
  ignored_count: 0,
}

const mockMutateReport = vi.fn()
const mockMutateIgnored = vi.fn()
const mockDeleteTag = vi.fn()
const mockHealthIgnore = vi.fn()
const mockHealthUnignore = vi.fn()
const mockCreateAlias = vi.fn()
const mockDeleteImplication = vi.fn()

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('swr', () => ({
  default: vi.fn((key: unknown) => {
    if (key === 'tags/health') return { data: h.report, mutate: mockMutateReport }
    if (key === 'tags/health/ignored') return { data: h.ignored, mutate: mockMutateIgnored }
    return { data: undefined, mutate: vi.fn() }
  }),
}))

vi.mock('@/lib/api', () => ({
  api: {
    tags: {
      list: vi.fn().mockResolvedValue({ tags: [], total: 0 }),
      listAliases: vi.fn().mockResolvedValue([]),
      createAlias: (...args: unknown[]) => mockCreateAlias(...args),
      deleteAlias: vi.fn(),
      listImplications: vi.fn().mockResolvedValue([]),
      createImplication: vi.fn(),
      deleteImplication: (...args: unknown[]) => mockDeleteImplication(...args),
      getTranslations: vi.fn().mockResolvedValue({}),
      upsertTranslation: vi.fn(),
      health: vi.fn(),
      healthIgnore: (...args: unknown[]) => mockHealthIgnore(...args),
      healthUnignore: (...args: unknown[]) => mockHealthUnignore(...args),
      healthIgnored: vi.fn(),
      deleteTag: (...args: unknown[]) => mockDeleteTag(...args),
    },
  },
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { role: h.profileRole } }),
}))

import TagHealthPanel from '@/components/TagHealthPanel'
import TagsPage from '@/app/tags/page'

describe('TagHealthPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.report = {
      orphans: [{ id: 1, namespace: 'general', name: 'orphan_tag', count: 0 }],
      orphans_total: 5,
      duplicates: [
        {
          key: 'general:bluehair',
          tags: [
            { id: 2, namespace: 'general', name: 'blue_hair', count: 120 },
            { id: 3, namespace: 'general', name: 'blue-hair', count: 2 },
          ],
        },
      ],
      implication_cycles: [
        {
          key: '10-11',
          path: [
            { id: 10, namespace: 'general', name: 'a' },
            { id: 11, namespace: 'general', name: 'b' },
          ],
        },
      ],
      ignored_count: 1,
    }
    h.ignored = { keys: ['dup:general:other'] }
    mockDeleteTag.mockResolvedValue({ status: 'ok' })
    mockHealthIgnore.mockResolvedValue({ status: 'ok' })
    mockHealthUnignore.mockResolvedValue({ status: 'ok' })
    mockCreateAlias.mockResolvedValue({ status: 'ok' })
    mockDeleteImplication.mockResolvedValue({ status: 'ok' })
  })

  it('renders orphans, duplicates, and cycles sections with data', () => {
    render(<TagHealthPanel />)

    expect(screen.getByText('tags.health.orphans')).toBeInTheDocument()
    expect(screen.getByText(/orphan_tag/)).toBeInTheDocument()

    expect(screen.getByText('tags.health.duplicates')).toBeInTheDocument()
    expect(screen.getByText(/blue_hair/)).toBeInTheDocument()
    expect(screen.getByText(/blue-hair/)).toBeInTheDocument()
    expect(screen.getByText('tags.health.canonical')).toBeInTheDocument()

    expect(screen.getByText('tags.health.cycles')).toBeInTheDocument()
    expect(screen.getAllByText('general:a').length).toBeGreaterThan(0)
    expect(screen.getByText('general:b')).toBeInTheDocument()
  })

  it('delete button on an orphan calls deleteTag and refreshes the report', async () => {
    render(<TagHealthPanel />)

    fireEvent.click(screen.getByRole('button', { name: 'tags.health.delete' }))

    await waitFor(() => expect(mockDeleteTag).toHaveBeenCalledWith(1))
    await waitFor(() => expect(mockMutateReport).toHaveBeenCalled())
  })

  it('ignore button on an orphan calls healthIgnore with the orphan key', async () => {
    render(<TagHealthPanel />)

    const ignoreButtons = screen.getAllByRole('button', { name: 'tags.health.ignore' })
    fireEvent.click(ignoreButtons[0])

    await waitFor(() => expect(mockHealthIgnore).toHaveBeenCalledWith('orphan:1'))
  })

  it('set-alias button creates an alias for the non-canonical duplicate targeting the highest-count tag', async () => {
    render(<TagHealthPanel />)

    fireEvent.click(screen.getByRole('button', { name: 'tags.health.setAlias' }))

    await waitFor(() =>
      expect(mockCreateAlias).toHaveBeenCalledWith('general', 'blue-hair', 2),
    )
  })

  it('break-link button on a cycle edge calls deleteImplication', async () => {
    render(<TagHealthPanel />)

    const breakButtons = screen.getAllByRole('button', { name: 'tags.health.breakLink' })
    fireEvent.click(breakButtons[0])

    await waitFor(() => expect(mockDeleteImplication).toHaveBeenCalledWith(10, 11))
  })

  it('restore button on an ignored item calls healthUnignore', async () => {
    render(<TagHealthPanel />)

    fireEvent.click(screen.getByRole('button', { name: 'tags.health.unignore' }))

    await waitFor(() => expect(mockHealthUnignore).toHaveBeenCalledWith('dup:general:other'))
  })

  it('shows empty-state text for each section when the report has no issues', () => {
    h.report = emptyReport
    h.ignored = { keys: [] }

    render(<TagHealthPanel />)

    expect(screen.getByText('tags.health.orphansEmpty')).toBeInTheDocument()
    expect(screen.getByText('tags.health.duplicatesEmpty')).toBeInTheDocument()
    expect(screen.getByText('tags.health.cyclesEmpty')).toBeInTheDocument()
    expect(screen.getByText('tags.health.ignoredEmpty')).toBeInTheDocument()
  })
})

describe('TagsPage health tab visibility', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDeleteTag.mockResolvedValue({ status: 'ok' })
  })

  it('does not show the Health tab for non-admin users', () => {
    h.profileRole = 'viewer'
    render(<TagsPage />)

    expect(screen.queryByText('tags.tabHealth')).not.toBeInTheDocument()
    expect(screen.queryByText('tags.tabBrowse')).not.toBeInTheDocument()
  })

  it('shows the Health tab for admin users', () => {
    h.profileRole = 'admin'
    render(<TagsPage />)

    expect(screen.getByText('tags.tabHealth')).toBeInTheDocument()
    expect(screen.getByText('tags.tabBrowse')).toBeInTheDocument()
  })
})
