import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { TrashGallery } from '@/lib/types'

// Stateful URL: replace() updates the query string and re-renders subscribers.
const nav = vi.hoisted(() => {
  const state = { search: '', listeners: new Set<() => void>() }
  return {
    state,
    replace: (url: string) => {
      state.search = url.includes('?') ? url.slice(url.indexOf('?') + 1) : ''
      state.listeners.forEach((l) => l())
    },
  }
})

vi.mock('next/navigation', async () => {
  const React = await import('react')
  const router = { push: vi.fn(), replace: vi.fn(nav.replace), back: vi.fn() }
  return {
    useRouter: () => router,
    useSearchParams: () => {
      const search = React.useSyncExternalStore(
        (cb) => {
          nav.state.listeners.add(cb)
          return () => nav.state.listeners.delete(cb)
        },
        () => nav.state.search,
        () => nav.state.search,
      )
      return React.useMemo(() => new URLSearchParams(search), [search])
    },
    usePathname: () => '/trash',
  }
})

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'en' }),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const api = vi.hoisted(() => ({
  library: {
    trashList: vi.fn(),
    trashSummary: vi.fn(),
    trashRestore: vi.fn(),
    trashPurge: vi.fn(),
    trashPreview: vi.fn(),
    restore: vi.fn(),
    permanentDelete: vi.fn(),
    emptyTrash: vi.fn(),
  },
  settings: { getFeatures: vi.fn() },
}))

vi.mock('@/lib/api', () => ({ api }))

import TrashPage from '@/app/trash/page'

function makeGallery(id: number): TrashGallery {
  return {
    id,
    source: 'local',
    source_id: `sid-${id}`,
    title: `Gallery ${id}`,
    title_jpn: null,
    pages: 10,
    cover_thumb: null,
    deleted_at: new Date().toISOString(),
    deleted_reason: 'user',
    deleted_by: { id: 1, username: 'alice' },
    merged_into: null,
  } as unknown as TrashGallery
}

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <TrashPage />
    </SWRConfig>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  nav.state.search = ''
  api.library.trashSummary.mockResolvedValue({
    count: 2,
    logical_bytes: 2048,
    reclaimable_bytes: 1024,
    next_expiry_at: null,
    sources: ['local'],
    purge: null,
  })
  api.settings.getFeatures.mockResolvedValue({ trash_enabled: true, trash_retention_days: 30 })
  api.library.trashList.mockResolvedValue({
    total: 2,
    galleries: [makeGallery(11), makeGallery(12)],
  })
  api.library.trashRestore.mockResolvedValue({ status: 'ok', affected: 2 })
  api.library.trashPreview.mockResolvedValue({
    gallery: makeGallery(11),
    media: { total_size: 0, counts: { image: 0, gif: 0, video: 0 } },
    images: [],
    images_total: 0,
    page: 1,
  })
})

describe('Trash page', () => {
  it('test_trash_page_total_over_50_renders_pagination_and_page_2_requests_offset_50', async () => {
    api.library.trashList.mockImplementation(async ({ offset }: { offset: number }) => ({
      total: 120,
      galleries: [makeGallery(offset + 1)],
    }))
    renderPage()
    await screen.findByTestId('trash-row-1')
    expect(api.library.trashList).toHaveBeenCalledWith({ limit: 50, offset: 0 })

    fireEvent.click(screen.getByRole('button', { name: 'Page 2' }))

    // The page lives in the URL (1-based), then drives the offset
    expect(nav.state.search).toBe('page=2')
    await screen.findByTestId('trash-row-51')
    expect(api.library.trashList).toHaveBeenCalledWith({ limit: 50, offset: 50 })
  })

  it('test_trash_page_total_50_or_less_does_not_render_pagination', async () => {
    renderPage()
    await screen.findByTestId('trash-row-11')
    expect(screen.queryByRole('button', { name: 'Page 2' })).toBeNull()
  })

  it('test_trash_page_select_two_rows_restore_selected_sends_gallery_ids', async () => {
    renderPage()
    await screen.findByTestId('trash-row-11')
    fireEvent.click(screen.getByTestId('trash-select-mode'))
    fireEvent.click(screen.getByTestId('trash-select-11'))
    fireEvent.click(screen.getByTestId('trash-select-12'))
    fireEvent.click(screen.getByTestId('trash-restore-selected'))

    await waitFor(() => expect(api.library.trashRestore).toHaveBeenCalledTimes(1))
    expect(api.library.trashRestore).toHaveBeenCalledWith({ gallery_ids: [11, 12] })
  })

  it('test_trash_page_select_page_checks_every_row_on_the_page', async () => {
    renderPage()
    await screen.findByTestId('trash-row-11')
    fireEvent.click(screen.getByTestId('trash-select-mode'))
    fireEvent.click(screen.getByTestId('trash-select-page'))
    expect((screen.getByTestId('trash-select-11') as HTMLInputElement).checked).toBe(true)
    expect((screen.getByTestId('trash-select-12') as HTMLInputElement).checked).toBe(true)
  })

  it('test_trash_page_delete_selected_confirms_then_purges_selected_ids', async () => {
    api.library.trashPurge.mockResolvedValue({ status: 'ok', affected: 1, deleted_dirs: 0 })
    renderPage()
    await screen.findByTestId('trash-row-11')
    fireEvent.click(screen.getByTestId('trash-select-mode'))
    fireEvent.click(screen.getByTestId('trash-select-12'))
    fireEvent.click(screen.getByTestId('trash-delete-selected'))
    expect(api.library.trashPurge).not.toHaveBeenCalled()

    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete Permanently' }))

    await waitFor(() => expect(api.library.trashPurge).toHaveBeenCalledWith([12]))
  })

  it('test_trash_page_restore_all_requires_confirm_then_sends_all_true', async () => {
    renderPage()
    await screen.findByTestId('trash-row-11')
    fireEvent.click(screen.getByTestId('trash-restore-all'))
    expect(api.library.trashRestore).not.toHaveBeenCalled()

    const dialog = await screen.findByRole('alertdialog')
    expect(dialog.textContent).toContain('2')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Restore all' }))

    await waitFor(() => expect(api.library.trashRestore).toHaveBeenCalledWith({ all: true }))
  })

  it('test_trash_page_empty_trash_dialog_text_contains_total_and_empties_on_confirm', async () => {
    api.library.trashList.mockResolvedValue({
      total: 137,
      galleries: [makeGallery(11)],
    })
    api.library.emptyTrash.mockResolvedValue({ status: 'ok' })
    renderPage()
    await screen.findByTestId('trash-row-11')
    fireEvent.click(screen.getByTestId('trash-empty'))

    const dialog = await screen.findByRole('alertdialog')
    expect(dialog.textContent).toContain('137')
    expect(api.library.emptyTrash).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Empty Trash' }))
    await waitFor(() => expect(api.library.emptyTrash).toHaveBeenCalledTimes(1))
  })

  it('test_trash_page_row_click_opens_preview_and_requests_page_1_limit_60', async () => {
    renderPage()
    fireEvent.click(await screen.findByTestId('trash-row-11'))

    await screen.findByTestId('trash-preview-sheet')
    await waitFor(() =>
      expect(api.library.trashPreview).toHaveBeenCalledWith(11, { page: 1, limit: 60 }),
    )
  })
})
