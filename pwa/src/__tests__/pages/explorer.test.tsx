import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { api } from '@/lib/api'

const replace = vi.fn()
const push = vi.fn()
let currentParams = ''

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(currentParams),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
  formatBytes: (value: number) => `${value} B`,
}))

vi.mock('@/lib/api', () => ({
  api: {
    explorer: {
      roots: vi.fn(),
      query: vi.fn(),
      createSelection: vi.fn(),
      bulkMetadata: vi.fn(),
      deleteSelection: vi.fn(),
      bulkAction: vi.fn(),
      mergePreview: vi.fn(),
      merge: vi.fn(),
      metadataHistory: vi.fn(),
      physicalEntries: vi.fn(),
      physicalPreviewUrl: vi.fn(),
      refreshPhysicalSize: vi.fn(),
      importPhysicalFolder: vi.fn(),
      galleryImages: vi.fn(),
      purgeImages: vi.fn(),
    },
    library: { hideImagesBatch: vi.fn(), restoreImagesBatch: vi.fn() },
    collections: { list: vi.fn() },
  },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/Skeleton', () => ({ SkeletonGrid: () => <div data-testid="skeleton-grid" /> }))

const mutate = vi.fn()
let swrResponses: Record<string, Record<string, unknown>> = {}
let swrCalls: Array<{ name: string; key: unknown; fetcher: unknown }> = []

vi.mock('swr', () => ({
  default: (key: unknown, fetcher: unknown) => {
    const name = Array.isArray(key) ? String(key[0]) : key === null ? '__null__' : String(key)
    swrCalls.push({ name, key, fetcher })
    return swrResponses[name] ?? { data: undefined, error: undefined, isLoading: false, mutate }
  },
}))

const roots = {
  virtual: {
    sources: [
      { id: 'local', label: 'Local', gallery_count: 2, logical_bytes: 300, unique_cas_bytes: 200 },
    ],
    collections: { count: 0, items: [] },
    artists: { count: 0, items: [] },
    saved_searches: { count: 0, items: [] },
    smart_views: { missing_metadata: 1, empty_galleries: 0, duplicate_pairs: 0, trash: true },
  },
  physical: [],
}

const galleries = {
  total: 2,
  offset: 0,
  limit: 60,
  items: [
    {
      id: 1,
      source: 'local',
      source_id: 'one',
      title: 'Gallery One',
      title_jpn: null,
      category: 'Manga',
      language: 'English',
      artist_id: null,
      uploader: null,
      visibility: 'public',
      pages: 2,
      cover_thumb: null,
      logical_bytes: 200,
      unique_cas_bytes: 200,
      is_favorited: false,
      my_rating: null,
      in_reading_list: false,
      deleted_at: null,
    },
    {
      id: 2,
      source: 'local',
      source_id: 'two',
      title: 'Gallery Two',
      title_jpn: null,
      category: 'Manga',
      language: null,
      artist_id: null,
      uploader: null,
      visibility: 'public',
      pages: 1,
      cover_thumb: null,
      logical_bytes: 100,
      unique_cas_bytes: 100,
      is_favorited: false,
      my_rating: null,
      in_reading_list: false,
      deleted_at: null,
    },
  ],
}

const imageSummary = {
  active_count: 2,
  hidden_count: 1,
  active_bytes: 5000,
  hidden_bytes: 700,
  hidden_reclaimable_bytes: 700,
}

function galleryImages(overrides: Record<string, unknown> = {}) {
  return {
    gallery_id: 1,
    source: 'local',
    source_id: 'one',
    total: 3,
    offset: 0,
    limit: 200,
    can_edit: true,
    summary: imageSummary,
    items: [
      {
        image_id: 11,
        page_num: 1,
        source_position: 1,
        filename: '001.webp',
        visibility: 'active',
        hidden_at: null,
        media_type: 'image',
        file_size: 2000,
        width: 1200,
        height: 1800,
        duration: null,
        storage: 'cas',
        shared: false,
        thumb_path: '/thumbs/001.webp',
        thumb_srcset: null,
        file_path: '/media/001.webp',
      },
      {
        image_id: 12,
        page_num: 2,
        source_position: 2,
        filename: '002.mp4',
        visibility: 'active',
        hidden_at: null,
        media_type: 'video',
        file_size: 3000,
        width: 1920,
        height: 1080,
        duration: 12,
        storage: 'cas',
        shared: true,
        thumb_path: '/thumbs/002.webp',
        thumb_srcset: null,
        file_path: '/media/002.mp4',
      },
      {
        image_id: 13,
        page_num: null,
        source_position: 3,
        filename: '003.png',
        visibility: 'hidden',
        hidden_at: '2026-10-29T00:00:00Z',
        media_type: 'image',
        file_size: 700,
        width: 800,
        height: 600,
        duration: null,
        storage: 'cas',
        shared: false,
        thumb_path: '/thumbs/003.webp',
        thumb_srcset: null,
        file_path: '/media/003.png',
      },
    ],
    ...overrides,
  }
}

const GALLERY_PARAMS = 'kind=gallery&id=1&source=local&sourceId=one&label=Gallery%20One'

function showGalleryImages(data: unknown = galleryImages()) {
  currentParams = GALLERY_PARAMS
  swrResponses['explorer-gallery-images'] = { data, error: undefined, isLoading: false, mutate }
}

function imageTiles() {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-testid="explorer-image-tile"]'))
}

function purgeResult(overrides: Record<string, unknown> = {}) {
  return {
    gallery_id: 1,
    dry_run: true,
    purgeable: 1,
    purged: 0,
    reclaim_bytes: 700,
    shared_kept: 0,
    skipped_external: 0,
    skipped_not_hidden: 0,
    skipped_pending: 0,
    skipped_missing: 0,
    blobs_deleted: 0,
    operation_id: null,
    ...overrides,
  }
}

describe('ExplorerWorkbench', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    swrCalls = []
    currentParams = ''
    localStorage.clear()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })
    swrResponses = {
      'explorer-roots': { data: roots, error: undefined, isLoading: false, mutate },
    }
  })

  it('renders the Workbench root and source capacity', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(screen.getByText('explorer.workbench')).toBeDefined()
    expect(screen.getAllByText('Local').length).toBeGreaterThan(0)
    expect(screen.getAllByText('300 B').length).toBeGreaterThan(0)
  })

  it('bounds the mobile content pane so its gallery area can scroll', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(screen.getByRole('main').className).toContain('h-[calc(100dvh-7rem-var(--sab)-var(--sat)/2)]')
    const contentPane = document.querySelector('[data-explorer-content-pane]')
    expect(contentPane?.className).toContain('h-full')
    expect(contentPane?.parentElement?.className).toContain('overflow-hidden')
  })

  it('renders Gallery images as compact full-width rows in list view', async () => {
    showGalleryImages()
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    // Grid first: tiles carry "#page · filename"; the list-only meta line is absent.
    expect(imageTiles()).toHaveLength(3)
    expect(screen.getByText('#1 · 001.webp')).toBeDefined()
    expect(screen.queryByText('#1 · 1200 × 1800 · 2000 B')).toBeNull()
    fireEvent.click(screen.getByLabelText('explorer.listView'))

    const rows = imageTiles()
    expect(rows).toHaveLength(3)
    expect(rows[0].className).toContain('w-full')
    expect(screen.getByText('#1 · 1200 × 1800 · 2000 B')).toBeDefined()
    expect(rows[0].querySelector('img')?.className).toContain('object-contain')
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('view=list'))
  })

  it('renders a URL-persisted list view on the first frame after returning from Reader', async () => {
    showGalleryImages()
    currentParams += '&view=list'
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    const rows = imageTiles()
    expect(rows).toHaveLength(3)
    expect(rows.every((row) => row.className.includes('w-full'))).toBe(true)
    expect(screen.getByText('#1 · 1200 × 1800 · 2000 B')).toBeDefined()
    expect(screen.queryByText('#1 · 001.webp')).toBeNull()
  })

  it('opens a Gallery image in Reader with one tap on coarse pointers', async () => {
    showGalleryImages()
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    await waitFor(() => expect(window.matchMedia).toHaveBeenCalled())

    fireEvent.click(imageTiles()[1])
    expect(push).toHaveBeenCalledWith(expect.stringContaining('/reader/'))
    expect(push).toHaveBeenCalledWith(expect.stringContaining('2'))
  })

  it('requests the Gallery images from the explorer images endpoint with the default filters', async () => {
    showGalleryImages()
    vi.mocked(api.explorer.galleryImages).mockResolvedValue(galleryImages() as never)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    const call = swrCalls.findLast((entry) => entry.name === 'explorer-gallery-images')!
    await (call.fetcher as (key: unknown) => Promise<unknown>)(call.key)
    expect(api.explorer.galleryImages).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ visibility: 'active', media: 'all', sort: 'page', direction: 'asc', offset: 0 }),
    )
  })

  it('opens the context menu with Hide when right-clicking an active image tile', async () => {
    showGalleryImages()
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    expect(screen.queryByTestId('explorer-context-menu')).toBeNull()

    fireEvent.contextMenu(imageTiles()[0])

    const menu = screen.getByTestId('explorer-context-menu')
    expect(within(menu).getByTestId('context-menu-hide')).toBeEnabled()
    expect(within(menu).getByTestId('context-menu-purge')).toBeDisabled()
    // Right-click on an unselected tile selects it first.
    expect(imageTiles()[0].getAttribute('aria-pressed')).toBe('true')
  })

  it('hides the selected images with the batch hide API', async () => {
    showGalleryImages()
    vi.mocked(api.library.hideImagesBatch).mockResolvedValue({ status: 'ok', hidden: 2, remaining_pages: 0 })
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.click(imageTiles()[0])
    fireEvent.click(imageTiles()[1], { ctrlKey: true })
    fireEvent.click(screen.getByTestId('action-hide'))

    await waitFor(() => expect(api.library.hideImagesBatch).toHaveBeenCalledWith('local', 'one', [11, 12]))
    await waitFor(() => expect(mutate).toHaveBeenCalled())
  })

  it('hides an image from the context menu', async () => {
    showGalleryImages()
    vi.mocked(api.library.hideImagesBatch).mockResolvedValue({ status: 'ok', hidden: 1, remaining_pages: 1 })
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.contextMenu(imageTiles()[1])
    fireEvent.click(screen.getByTestId('context-menu-hide'))

    await waitFor(() => expect(api.library.hideImagesBatch).toHaveBeenCalledWith('local', 'one', [12]))
  })

  it('keeps Purge disabled when the selection includes an active image', async () => {
    showGalleryImages()
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.click(imageTiles()[0])
    fireEvent.click(imageTiles()[2], { ctrlKey: true })

    expect(screen.getByTestId('action-purge')).toBeDisabled()
    fireEvent.click(screen.getByTestId('action-purge'))
    expect(api.explorer.purgeImages).not.toHaveBeenCalled()
  })

  it('previews with a dry run and then purges the selected hidden images', async () => {
    showGalleryImages()
    vi.mocked(api.explorer.purgeImages)
      .mockResolvedValueOnce(purgeResult() as never)
      .mockResolvedValueOnce(purgeResult({ dry_run: false, purged: 1, purgeable: 1, blobs_deleted: 1 }) as never)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.click(imageTiles()[2])
    expect(screen.getByTestId('action-purge')).toBeEnabled()
    fireEvent.click(screen.getByTestId('action-purge'))

    await waitFor(() => expect(screen.getByTestId('purge-purgeable').textContent).toBe('1'))
    expect(screen.getByTestId('purge-reclaim').textContent).toBe('700 B')
    expect(api.explorer.purgeImages).toHaveBeenCalledTimes(1)
    expect(api.explorer.purgeImages).toHaveBeenNthCalledWith(1, 1, { image_ids: [13], dry_run: true })

    fireEvent.click(screen.getByTestId('purge-confirm'))
    await waitFor(() => expect(api.explorer.purgeImages).toHaveBeenCalledTimes(2))
    expect(api.explorer.purgeImages).toHaveBeenNthCalledWith(2, 1, { image_ids: [13], dry_run: false })
    await waitFor(() => expect(screen.queryByTestId('purge-dialog')).toBeNull())
    expect(mutate).toHaveBeenCalled()
  })

  it('does not enable the purge confirmation when the dry run finds nothing purgeable', async () => {
    showGalleryImages()
    vi.mocked(api.explorer.purgeImages).mockResolvedValue(purgeResult({ purgeable: 0, skipped_external: 1 }) as never)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.click(imageTiles()[2])
    fireEvent.click(screen.getByTestId('action-purge'))

    await waitFor(() => expect(screen.getByTestId('purge-external').textContent).toBe('1'))
    expect(screen.getByTestId('purge-confirm')).toBeDisabled()
    expect(api.explorer.purgeImages).toHaveBeenCalledTimes(1)
  })

  it('empties all hidden images with an all_hidden purge', async () => {
    showGalleryImages()
    vi.mocked(api.explorer.purgeImages)
      .mockResolvedValueOnce(purgeResult({ purgeable: 4, reclaim_bytes: 1400 }) as never)
      .mockResolvedValueOnce(purgeResult({ dry_run: false, purged: 4 }) as never)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.click(screen.getByTestId('empty-hidden'))

    await waitFor(() => expect(screen.getByTestId('purge-purgeable').textContent).toBe('4'))
    expect(api.explorer.purgeImages).toHaveBeenNthCalledWith(1, 1, { all_hidden: true, dry_run: true })
    fireEvent.click(screen.getByTestId('purge-confirm'))
    await waitFor(() => expect(api.explorer.purgeImages).toHaveBeenNthCalledWith(2, 1, { all_hidden: true, dry_run: false }))
  })

  it('offers no hide or purge controls to a read-only collaborator', async () => {
    showGalleryImages(galleryImages({ can_edit: false }))
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(screen.queryByTestId('empty-hidden')).toBeNull()
    fireEvent.click(imageTiles()[2])
    expect(screen.queryByTestId('action-hide')).toBeNull()
    expect(screen.queryByTestId('action-purge')).toBeNull()
    fireEvent.contextMenu(imageTiles()[2])
    expect(screen.queryByTestId('context-menu-purge')).toBeNull()
  })

  it('offers sorting Galleries by size and sends sort size to the query', async () => {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    const select = screen.getByLabelText('explorer.sortBy') as HTMLSelectElement
    expect(Array.from(select.options).map((option) => option.value)).toContain('size')
    fireEvent.change(select, { target: { value: 'size' } })

    await waitFor(() => {
      const last = swrCalls.findLast((entry) => entry.name === 'explorer-query')!
      expect(JSON.parse((last.key as string[])[1])).toMatchObject({ sort: 'size' })
    })
  })

  it('offers sorting Gallery images by size and requests sort size from the images endpoint', async () => {
    showGalleryImages()
    vi.mocked(api.explorer.galleryImages).mockResolvedValue(galleryImages() as never)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    const select = screen.getByLabelText('explorer.sortBy') as HTMLSelectElement
    expect(Array.from(select.options).map((option) => option.value)).toEqual(['page', 'size'])
    fireEvent.change(select, { target: { value: 'size' } })

    await waitFor(() => {
      const last = swrCalls.findLast((entry) => entry.name === 'explorer-gallery-images')!
      expect((last.key as unknown[])[4]).toBe('size')
    })
    const last = swrCalls.findLast((entry) => entry.name === 'explorer-gallery-images')!
    await (last.fetcher as (key: unknown) => Promise<unknown>)(last.key)
    expect(api.explorer.galleryImages).toHaveBeenCalledWith(1, expect.objectContaining({ sort: 'size', direction: 'desc' }))
  })

  it('renders the empty inspector without requesting metadata history', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(screen.getByText('explorer.inspectorEmpty')).toBeDefined()
    expect(api.explorer.metadataHistory).not.toHaveBeenCalled()
  })

  it('shows an inline error and retries the failed roots request', async () => {
    swrResponses['explorer-roots'] = {
      data: undefined,
      error: new Error('Network error'),
      isLoading: false,
      mutate,
    }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(screen.getByText('Network error')).toBeDefined()
    fireEvent.click(screen.getByText('common.retry'))
    expect(mutate).toHaveBeenCalled()
  })

  it('desktop single click selects and double click enters a folder', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    const localCards = screen.getAllByText('Local')
    const contentCardLabel = localCards[localCards.length - 1]

    fireEvent.click(contentCardLabel)
    expect(screen.getByText('explorer.selectedCount')).toBeDefined()

    fireEvent.doubleClick(contentCardLabel)
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('kind=source'))
  })

  it('coarse pointer body tap enters a folder without starting selection', async () => {
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    await waitFor(() => expect(window.matchMedia).toHaveBeenCalled())
    const localCards = screen.getAllByText('Local')

    fireEvent.click(localCards[localCards.length - 1])
    await waitFor(() => expect(replace).toHaveBeenCalledWith(expect.stringContaining('kind=source')))
    expect(screen.queryByText('explorer.selectedCount')).toBeNull()
  })

  it('coarse pointer icon tap starts selection without entering the folder', async () => {
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    await waitFor(() => expect(window.matchMedia).toHaveBeenCalled())

    fireEvent.click(screen.getByLabelText('explorer.toggleSelection'))
    expect(screen.getByText('explorer.selectedCount')).toBeDefined()
    expect(replace).not.toHaveBeenCalledWith(expect.stringContaining('kind=source'))
  })

  it('supports Gallery multi-selection from the item icon in mobile list view', async () => {
    currentParams = 'kind=source&id=local&label=Local&view=list'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    await waitFor(() => expect(window.matchMedia).toHaveBeenCalled())

    fireEvent.click(screen.getAllByLabelText('explorer.toggleSelection')[0])
    expect(screen.getByText('explorer.selectedCount')).toBeDefined()
    expect(replace).not.toHaveBeenCalledWith(expect.stringContaining('kind=gallery'))
  })

  it('persists the column layout per device', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.click(screen.getByLabelText('explorer.columnLayout'))
    expect(localStorage.getItem('explorer_layout_mode:desktop')).toBe('finder')
  })

  it('materializes a query-wide selection', async () => {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    vi.mocked(api.explorer.createSelection).mockResolvedValue({
      selection_token: 'token-1',
      count: 2,
      expires_in: 1800,
    })
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.click(screen.getByText('explorer.selectAllResults'))
    await waitFor(() => expect(api.explorer.createSelection).toHaveBeenCalled())
    expect(screen.getByText('explorer.selectedCount')).toBeDefined()
    expect(screen.getAllByLabelText('explorer.toggleSelection')).toHaveLength(2)
  })

  it('moves content focus with arrows and opens the focused Gallery with Enter', async () => {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    await waitFor(() => expect(document.activeElement?.textContent).toContain('Gallery One'))
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    await waitFor(() => expect(document.activeElement?.textContent).toContain('Gallery Two'))
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('kind=gallery'))
  })

  it('toggles and extends keyboard selection independently from focus', async () => {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    fireEvent.keyDown(window, { key: ' ' })
    expect(screen.getByText('explorer.selectedCount')).toBeDefined()
    fireEvent.keyDown(window, { key: 'ArrowRight', shiftKey: true })
    expect(screen.getAllByLabelText('explorer.toggleSelection')).toHaveLength(2)
    expect(screen.getAllByText('explorer.selectedCount').length).toBeGreaterThan(0)
  })

  it('supports search, query-wide select all, and metadata keyboard shortcuts', async () => {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    vi.mocked(api.explorer.createSelection).mockResolvedValue({
      selection_token: 'keyboard-token',
      count: 2,
      expires_in: 1800,
    })
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.keyDown(window, { key: '/' })
    const search = screen.getByPlaceholderText('explorer.searchPlaceholder')
    expect(document.activeElement).toBe(search)
    fireEvent.blur(search)
    fireEvent.keyDown(window, { key: 'a', ctrlKey: true })
    await waitFor(() => expect(api.explorer.createSelection).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('explorer.selectedCount')).toBeDefined())
    fireEvent.keyDown(window, { key: 'F2' })
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'explorer.editMetadata' })).toBeDefined())
  })

  it('moves focus within the navigation pane with ArrowDown', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    const navigation = screen.getByRole('navigation', { name: 'explorer.libraryTree' })
    const buttons = within(navigation).getAllByRole('button')
    buttons[0].focus()

    fireEvent.keyDown(buttons[0], { key: 'ArrowDown' })
    expect(document.activeElement).toBe(buttons[1])
  })

  it('moves between column navigation sections and items with Left and Right', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    fireEvent.click(screen.getByLabelText('explorer.columnLayout'))

    const navigation = screen.getByRole('navigation', { name: 'explorer.finderColumns' })
    const sections = navigation.querySelector<HTMLElement>('[data-explorer-nav-pane="sections"]')
    const items = navigation.querySelector<HTMLElement>('[data-explorer-nav-pane="items"]')
    const sectionButton = within(sections!).getAllByRole('button')[0]
    sectionButton.focus()

    fireEvent.keyDown(sectionButton, { key: 'ArrowRight' })
    await waitFor(() => expect(document.activeElement).toBe(within(items!).getAllByRole('button')[0]))
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowLeft' })
    expect(document.activeElement).toBe(sectionButton)
  })

  it('cycles navigation, content, and inspector panes with F6', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    const navigation = screen.getByRole('navigation', { name: 'explorer.libraryTree' })
    const navigationButton = within(navigation).getAllByRole('button')[0]
    navigationButton.focus()

    fireEvent.keyDown(navigationButton, { key: 'F6' })
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-explorer-item][tabindex="0"]')))
    fireEvent.keyDown(document.activeElement!, { key: 'F6' })
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-explorer-inspector]')))
    fireEvent.keyDown(document.activeElement!, { key: 'F6' })
    expect(document.activeElement?.closest('[data-explorer-navigation]')).toBe(navigation)
  })

  it('opens the shortcut reference with question mark', async () => {
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.keyDown(window, { key: '?' })
    expect(screen.getByRole('dialog', { name: 'explorer.keyboardShortcuts' })).toBeDefined()
    expect(screen.getByText('Shift + ↑ ↓ ← →')).toBeDefined()
  })

  it('moves selected Galleries to Trash with the Delete shortcut', async () => {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.explorer.deleteSelection).mockResolvedValue({
      operation_id: 'delete-op',
      status: 'completed',
      affected: 1,
      skipped_active_downloads: [],
    })
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    fireEvent.keyDown(window, { key: ' ' })
    await waitFor(() => expect(screen.getByText('explorer.selectedCount')).toBeDefined())
    fireEvent.keyDown(window, { key: 'Delete' })
    await waitFor(() => expect(api.explorer.deleteSelection).toHaveBeenCalledWith({ gallery_ids: [1] }))
  })

  it('returns to the Workbench root with Backspace', async () => {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    fireEvent.keyDown(window, { key: 'Backspace' })
    expect(replace).toHaveBeenCalledWith('/explorer?view=grid')
  })

  const categoryRoots = {
    ...roots,
    virtual: {
      ...roots.virtual,
      categories: {
        uncategorized: 3,
        items: [
          { id: 'Cosplay', label: 'Cosplay', gallery_count: 5, registered: true },
          { id: 'Legacy', label: 'Legacy', gallery_count: 1, registered: false },
        ],
      },
    },
  }
  const categoryRegistry = {
    categories: [
      { id: 2, name: 'Manga', color: '#fff', sort_order: 2, is_builtin: true, gallery_count: 2 },
      { id: 1, name: 'Cosplay', color: '#000', sort_order: 1, is_builtin: true, gallery_count: 5 },
    ],
    palette: [],
    uncategorized_count: 3,
  }

  async function openMetadataForTwoGalleries(categories: [string | null, string | null]) {
    currentParams = 'kind=source&id=local&label=Local'
    swrResponses['explorer-roots'] = { data: categoryRoots, error: undefined, isLoading: false, mutate }
    swrResponses['gallery-categories'] = { data: categoryRegistry, error: undefined, isLoading: false, mutate }
    swrResponses['explorer-query'] = {
      data: { ...galleries, items: galleries.items.map((item, index) => ({ ...item, category: categories[index] })) },
      error: undefined,
      isLoading: false,
      mutate,
    }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    fireEvent.keyDown(window, { key: ' ' })
    fireEvent.keyDown(window, { key: 'ArrowRight', shiftKey: true })
    fireEvent.keyDown(window, { key: 'F2' })
    return await screen.findByRole('dialog', { name: 'explorer.editMetadata' })
  }

  it('renders the Categories section with counts and the Uncategorized entry from roots', async () => {
    swrResponses['explorer-roots'] = { data: categoryRoots, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    const tree = screen.getByRole('navigation', { name: 'explorer.libraryTree' })
    expect(within(tree).getByText('explorer.categories')).toBeDefined()
    const uncategorized = within(tree).getByText('explorer.uncategorized').closest('button')!
    expect(within(uncategorized).getByText('3')).toBeDefined()
    expect(within(tree).getByText('Cosplay').closest('button')!.textContent).toContain('5')
    expect(within(tree).getByText('Legacy').closest('button')!.getAttribute('title')).toBe('explorer.unregisteredCategory')
  })

  it('clicking Uncategorized queries node_kind category with the __uncategorized__ sentinel', async () => {
    swrResponses['explorer-roots'] = { data: categoryRoots, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    const view = render(<ExplorerPage />)

    const tree = screen.getByRole('navigation', { name: 'explorer.libraryTree' })
    fireEvent.click(within(tree).getByText('explorer.uncategorized'))
    const url = replace.mock.calls.at(-1)?.[0] as string
    expect(url).toContain('kind=category')
    expect(url).toContain('id=__uncategorized__')

    view.unmount()
    currentParams = url.split('?')[1]
    swrCalls = []
    swrResponses['explorer-query'] = { data: galleries, error: undefined, isLoading: false, mutate }
    render(<ExplorerPage />)
    const last = swrCalls.findLast((entry) => entry.name === 'explorer-query' && entry.key)!
    expect(JSON.parse((last.key as string[])[1])).toMatchObject({ node_kind: 'category', node_id: '__uncategorized__' })
  })

  it('metadata dialog category is a select of registry names and submits mode set with the chosen value', async () => {
    vi.mocked(api.explorer.bulkMetadata).mockResolvedValue({ operation_id: 'op', status: 'done', selection_count: 2, changed_fields: 2 })
    const dialog = await openMetadataForTwoGalleries(['Manga', 'Manga'])
    const select = within(dialog).getByLabelText('category') as HTMLSelectElement
    expect(select.tagName).toBe('SELECT')
    expect(Array.from(select.options).map((option) => option.value)).toEqual(['Cosplay', 'Manga'])
    expect(select.value).toBe('Manga')

    fireEvent.change(within(dialog).getByLabelText('category mode'), { target: { value: 'set' } })
    fireEvent.change(select, { target: { value: 'Cosplay' } })
    fireEvent.click(within(dialog).getByText('common.save'))

    await waitFor(() => expect(api.explorer.bulkMetadata).toHaveBeenCalled())
    expect(vi.mocked(api.explorer.bulkMetadata).mock.calls[0][0].fields.category).toEqual({ mode: 'set', value: 'Cosplay' })
  })

  it('metadata dialog cannot submit an empty category with mode set when the selection has mixed categories', async () => {
    const dialog = await openMetadataForTwoGalleries(['Manga', 'Cosplay'])
    const select = within(dialog).getByLabelText('category') as HTMLSelectElement
    expect(select.value).toBe('')
    expect(within(dialog).getByText('explorer.mixedValues')).toBeDefined()

    fireEvent.change(within(dialog).getByLabelText('category mode'), { target: { value: 'set' } })
    const save = within(dialog).getByText('common.save').closest('button') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.click(save)
    expect(api.explorer.bulkMetadata).not.toHaveBeenCalled()

    fireEvent.change(select, { target: { value: 'Cosplay' } })
    expect(save.disabled).toBe(false)
  })
})
