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
    },
    library: { listGalleryFiles: vi.fn() },
    collections: { list: vi.fn() },
  },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/Skeleton', () => ({ SkeletonGrid: () => <div data-testid="skeleton-grid" /> }))

const mutate = vi.fn()
let swrResponses: Record<string, Record<string, unknown>> = {}

vi.mock('swr', () => ({
  default: (key: unknown) => {
    const name = Array.isArray(key) ? String(key[0]) : key === null ? '__null__' : String(key)
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

const galleryFiles = {
  gallery_id: 1,
  source: 'local',
  source_id: 'one',
  title: 'Gallery One',
  category: 'Manga',
  total_files: 2,
  files: [
    {
      filename: '001.webp',
      page_num: 1,
      width: 1200,
      height: 1800,
      file_size: 2000,
      media_type: 'image/webp',
      thumb_path: '/thumbs/001.webp',
      file_path: null,
      is_symlink: false,
      is_broken: false,
      symlink_target: null,
    },
    {
      filename: '002.mp4',
      page_num: 2,
      width: 1920,
      height: 1080,
      file_size: 3000,
      media_type: 'video/mp4',
      thumb_path: '/thumbs/002.webp',
      file_path: null,
      is_symlink: false,
      is_broken: false,
      symlink_target: null,
    },
  ],
}

describe('ExplorerWorkbench', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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

  it('renders Gallery files as compact full-width rows in list view', async () => {
    currentParams = 'kind=gallery&id=1&source=local&sourceId=one&label=Gallery%20One'
    swrResponses['explorer-gallery-files'] = { data: galleryFiles, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(document.querySelectorAll('[data-explorer-file-view="grid"]')).toHaveLength(2)
    fireEvent.click(screen.getByLabelText('explorer.listView'))

    const rows = document.querySelectorAll<HTMLElement>('[data-explorer-file-view="list"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].className).toContain('w-full')
    expect(screen.getByText('#1 · 1200 × 1800 · 2000 B')).toBeDefined()
    expect(rows[0].querySelector('img')?.className).toContain('object-contain')
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('view=list'))
  })

  it('renders a URL-persisted list view on the first frame after returning from Reader', async () => {
    currentParams = 'kind=gallery&id=1&source=local&sourceId=one&label=Gallery%20One&view=list'
    swrResponses['explorer-gallery-files'] = { data: galleryFiles, error: undefined, isLoading: false, mutate }
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)

    expect(document.querySelectorAll('[data-explorer-file-view="list"]')).toHaveLength(2)
    expect(document.querySelector('[data-explorer-file-view="grid"]')).toBeNull()
  })

  it('opens a Gallery file with one tap on coarse pointers', async () => {
    currentParams = 'kind=gallery&id=1&source=local&sourceId=one&label=Gallery%20One'
    swrResponses['explorer-gallery-files'] = { data: galleryFiles, error: undefined, isLoading: false, mutate }
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList)
    const { default: ExplorerPage } = await import('@/app/explorer/page')
    render(<ExplorerPage />)
    await waitFor(() => expect(window.matchMedia).toHaveBeenCalled())

    fireEvent.click(document.querySelectorAll<HTMLElement>('[data-explorer-file-view="grid"]')[0])
    expect(push).toHaveBeenCalledWith(expect.stringContaining('/reader/'))
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
})
