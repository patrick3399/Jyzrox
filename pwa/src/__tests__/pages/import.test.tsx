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

describe('ImportPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockBatchScanTrigger.mockResolvedValue({
      matches: [
        {
          rel_path: 'Alice/Gallery',
          abs_path: '/mnt/media/Alice/Gallery',
          artist: 'Alice',
          title: 'Gallery',
          file_count: 3,
        },
      ],
      unmatched: [],
    })
    mockBatchStartTrigger.mockResolvedValue({ batch_id: 'batch-1' })
  })

  it('does not render batch Copy/Link or scan schedule controls', async () => {
    const { default: ImportPage } = await import('@/app/import/page')
    render(<ImportPage />)

    expect(screen.queryByText('import.batch.modeCopy')).toBeNull()
    expect(screen.queryByText('import.batch.modeLink')).toBeNull()
    expect(screen.queryByText('import.scan.autoEnabled')).toBeNull()
    expect(screen.queryByText('import.scan.intervalLabel')).toBeNull()
  })

  it('starts batch import with copy mode', async () => {
    const { default: ImportPage } = await import('@/app/import/page')
    render(<ImportPage />)

    fireEvent.click(screen.getByText('import.zoneB.selectFolder'))
    fireEvent.click(screen.getByText('/mnt/media/{artist}/{_}/{title}'))
    fireEvent.click(screen.getByText('import.folderPicker.select'))

    fireEvent.click(screen.getByText('import.batch.scan'))
    await screen.findByText('import.batch.importAll 1')
    fireEvent.click(screen.getByText('import.batch.importAll 1'))

    await waitFor(() => {
      expect(mockBatchStartTrigger).toHaveBeenCalledWith({
        rootDir: '/mnt/media/{artist}/{_}/{title}',
        mode: 'copy',
        galleries: [{ path: '/mnt/media/Alice/Gallery', artist: 'Alice', title: 'Gallery' }],
      })
    })
  })

  it('roots the folder picker pattern example in a real mount, not a baked-in path', async () => {
    const { default: ImportPage } = await import('@/app/import/page')
    render(<ImportPage />)

    fireEvent.click(screen.getByText('import.zoneB.selectFolder'))

    // The example must be built from the host's own mount points; a hardcoded
    // path would name a directory that exists on one developer's machine only.
    expect(screen.getByText('/mnt/media/{artist}/{_}/{title}')).toBeInTheDocument()
    expect(screen.queryByText(/ssd-data/)).toBeNull()
  })
})
