import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }))

vi.mock('next/navigation', async () => {
  const React = await import('react')
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

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

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
import { ApiError } from '@/lib/api/client'

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

function summary(purge: { done: number; total: number } | null = null) {
  return {
    count: 2,
    logical_bytes: 2048,
    reclaimable_bytes: 1024,
    next_expiry_at: null,
    sources: ['local', 'other'],
    purge,
  }
}

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <TrashPage />
    </SWRConfig>,
  )
}

async function openEmptyConfirm() {
  await screen.findByTestId('trash-row-11')
  fireEvent.click(screen.getByTestId('trash-empty'))
  return screen.findByRole('alertdialog')
}

beforeEach(() => {
  vi.clearAllMocks()
  nav.state.search = ''
  router.replace.mockImplementation(nav.replace)
  api.settings.getFeatures.mockResolvedValue({ trash_enabled: true, trash_retention_days: 30 })
  api.library.trashList.mockResolvedValue({
    total: 2,
    galleries: [makeGallery(11), makeGallery(12)],
  })
  api.library.trashSummary.mockResolvedValue(summary())
  api.library.trashRestore.mockResolvedValue({ status: 'ok', affected: 2 })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Trash page filters', () => {
  it('test_trash_page_typing_in_search_replaces_url_with_q_after_300ms_debounce', async () => {
    renderPage()
    await screen.findByTestId('trash-row-11')

    vi.useFakeTimers()
    fireEvent.change(screen.getByTestId('trash-search'), { target: { value: 'foo' } })
    act(() => {
      vi.advanceTimersByTime(299)
    })
    expect(router.replace).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(router.replace).toHaveBeenCalledTimes(1)
    expect(router.replace).toHaveBeenCalledWith('/trash?q=foo', { scroll: false })
  })

  it('test_trash_page_q_in_url_passes_q_to_trash_list_and_summary', async () => {
    nav.state.search = 'q=foo'
    renderPage()
    await screen.findByTestId('trash-row-11')
    await waitFor(() => expect(api.library.trashSummary).toHaveBeenCalledWith({ q: 'foo' }))
    expect(api.library.trashList).toHaveBeenCalledWith({ limit: 50, offset: 0, q: 'foo' })
    expect((screen.getByTestId('trash-search') as HTMLInputElement).value).toBe('foo')
  })

  it('test_trash_page_reason_select_replaces_url_with_reason', async () => {
    renderPage()
    await screen.findByTestId('trash-row-11')
    fireEvent.change(screen.getByTestId('trash-filter-reason'), { target: { value: 'merged' } })
    expect(router.replace).toHaveBeenCalledWith('/trash?reason=merged', { scroll: false })
    await waitFor(() =>
      expect(api.library.trashList).toHaveBeenCalledWith({ limit: 50, offset: 0, reason: 'merged' }),
    )
  })

  it('test_trash_page_empty_with_active_filter_shows_filtered_confirm_and_sends_filters', async () => {
    nav.state.search = 'q=foo'
    api.library.emptyTrash.mockResolvedValue({ status: 'queued', total: 2 })
    renderPage()
    const dialog = await openEmptyConfirm()
    expect(dialog.textContent).toContain('matching the current filters')
    expect(api.library.emptyTrash).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Empty Trash' }))
    await waitFor(() => expect(api.library.emptyTrash).toHaveBeenCalledWith({ q: 'foo' }))
  })

  it('test_trash_page_empty_without_filter_uses_unfiltered_confirm', async () => {
    api.library.emptyTrash.mockResolvedValue({ status: 'queued', total: 2 })
    renderPage()
    const dialog = await openEmptyConfirm()
    expect(dialog.textContent).not.toContain('matching the current filters')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Empty Trash' }))
    await waitFor(() => expect(api.library.emptyTrash).toHaveBeenCalledWith({}))
  })

  it('test_trash_page_empty_queued_response_shows_purge_queued_toast', async () => {
    api.library.emptyTrash.mockResolvedValue({ status: 'queued', total: 2 })
    renderPage()
    const dialog = await openEmptyConfirm()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Empty Trash' }))
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Permanent deletion started in the background'),
    )
  })

  it('test_trash_page_empty_409_shows_purge_already_running_toast', async () => {
    api.library.emptyTrash.mockRejectedValue(new ApiError('conflict', 409, null))
    renderPage()
    const dialog = await openEmptyConfirm()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Empty Trash' }))
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('A permanent deletion is already running'),
    )
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('test_trash_page_summary_purge_running_shows_progress_and_disables_empty_and_restore_all', async () => {
    api.library.trashSummary.mockResolvedValue(summary({ done: 50, total: 200 }))
    renderPage()
    const progress = await screen.findByTestId('trash-purge-progress')
    expect(progress.textContent).toContain('50')
    expect(progress.textContent).toContain('200')
    expect((screen.getByTestId('trash-empty') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByTestId('trash-restore-all') as HTMLButtonElement).disabled).toBe(true)
  })

  it('test_trash_page_no_purge_in_summary_hides_progress_and_enables_buttons', async () => {
    renderPage()
    await screen.findByTestId('trash-summary')
    expect(screen.queryByTestId('trash-purge-progress')).toBeNull()
    expect((screen.getByTestId('trash-empty') as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByTestId('trash-restore-all') as HTMLButtonElement).disabled).toBe(false)
  })

  it('test_trash_page_restore_all_with_filter_sends_all_true_and_filter', async () => {
    nav.state.search = 'q=foo'
    renderPage()
    await screen.findByTestId('trash-row-11')
    fireEvent.click(screen.getByTestId('trash-restore-all'))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog.textContent).toContain('matching the current filters')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Restore all' }))
    await waitFor(() =>
      expect(api.library.trashRestore).toHaveBeenCalledWith({ all: true, q: 'foo' }),
    )
  })
})
