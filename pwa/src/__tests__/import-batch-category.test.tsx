import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockBatchScanTrigger = vi.fn()
const mockBatchStartTrigger = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

vi.mock('@/hooks/useCategoryRegistry', () => ({
  useCategoryRegistry: () => ({
    data: {
      categories: [
        { id: 1, name: 'Cosplay', color: 'red', sort_order: 8, is_builtin: true, gallery_count: 0 },
        { id: 2, name: 'Manga', color: 'orange', sort_order: 2, is_builtin: true, gallery_count: 0 },
      ],
      palette: ['red', 'orange'],
    },
  }),
}))

vi.mock('@/hooks/useImport', () => ({
  useBrowseFs: () => ({ data: { parent: null, entries: [] }, isLoading: false }),
  useMountPoints: () => ({
    data: { mounts: [{ name: 'media', path: '/mnt/media', type: 'disk' }] },
    isLoading: false,
  }),
  useBatchScan: () => ({ trigger: mockBatchScanTrigger, isMutating: false }),
  useBatchStart: () => ({ trigger: mockBatchStartTrigger }),
  useBatchProgress: () => ({ data: undefined }),
  useLibraries: () => ({ data: [], mutate: vi.fn() }),
  useMonitorStatus: () => ({ data: { running: false }, mutate: vi.fn() }),
  useAddLibrary: () => ({ trigger: vi.fn() }),
  useRemoveLibrary: () => ({ trigger: vi.fn() }),
  useToggleMonitor: () => ({ trigger: vi.fn(), isMutating: false }),
  useRescanLibraryPath: () => ({ trigger: vi.fn() }),
  useRecentImports: () => ({ data: [] }),
}))

async function renderAndScan() {
  const { default: ImportPage } = await import('@/app/import/page')
  render(<ImportPage />)
  fireEvent.click(screen.getByText('import.zoneB.selectFolder'))
  fireEvent.click(screen.getByText('/mnt/media/{artist}/{_}/{title}'))
  fireEvent.click(screen.getByText('import.folderPicker.select'))
  fireEvent.click(screen.getByText('import.batch.scan'))
  await screen.findByText('import.batch.importAll 2')
}

describe('Batch import category select', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockBatchScanTrigger.mockResolvedValue({
      matches: [
        {
          rel_path: 'cosplay/A/G1',
          abs_path: '/mnt/media/cosplay/A/G1',
          artist: 'A',
          category: 'cosplay',
          category_resolved: 'Cosplay',
          title: 'G1',
          file_count: 3,
        },
        {
          rel_path: 'Novel/B/G2',
          abs_path: '/mnt/media/Novel/B/G2',
          artist: 'B',
          category: 'Novel',
          category_resolved: null,
          title: 'G2',
          file_count: 2,
        },
      ],
      unmatched: [],
    })
    mockBatchStartTrigger.mockResolvedValue({ batch_id: 'batch-1' })
  })

  it('test_batch_preview_category_is_select_preselected_with_resolved_name_or_uncategorized', async () => {
    await renderAndScan()
    const selects = screen.getAllByRole('combobox') as HTMLSelectElement[]
    expect(selects).toHaveLength(2)
    expect(selects[0].value).toBe('Cosplay')
    expect(selects[1].value).toBe('')
  })

  it('test_batch_preview_flags_only_the_unregistered_row', async () => {
    await renderAndScan()
    expect(screen.getByText(/Novel — import\.batch\.categoryUnregistered/)).toBeInTheDocument()
    expect(screen.queryByText(/cosplay — import\.batch\.categoryUnregistered/)).toBeNull()
  })

  it('test_batch_start_sends_selected_category_and_null_for_unregistered', async () => {
    await renderAndScan()
    fireEvent.click(screen.getByText('import.batch.importAll 2'))

    await waitFor(() => expect(mockBatchStartTrigger).toHaveBeenCalled())
    const arg = mockBatchStartTrigger.mock.calls[0][0]
    expect(arg.galleries.map((g: { category: string | null }) => g.category)).toEqual([
      'Cosplay',
      null,
    ])
  })

  it('test_batch_start_uses_category_the_user_picked_from_the_select', async () => {
    await renderAndScan()
    const selects = screen.getAllByRole('combobox') as HTMLSelectElement[]
    fireEvent.change(selects[1], { target: { value: 'Manga' } })
    fireEvent.click(screen.getByText('import.batch.importAll 2'))

    await waitFor(() => expect(mockBatchStartTrigger).toHaveBeenCalled())
    const arg = mockBatchStartTrigger.mock.calls[0][0]
    expect(arg.galleries[1].category).toBe('Manga')
  })
})
