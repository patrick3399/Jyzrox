/**
 * Regression test: the E-Hentai search suggestion dropdown must be dismissible.
 *
 * Bug: the dropdown rendered whenever the input still held an unfinished token
 * with matching tags — it had no open/closed state of its own. The outside-click
 * and Escape handlers only closed the *history* dropdown, so the suggestion list
 * stayed pinned over the category chips below the search bar until the input
 * was cleared. Picking a suggestion did not help either: the applied value ends
 * in a separator space, which the fragment parser read as a still-open token and
 * re-queried, showing the same list again.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  usePathname: () => '/e-hentai',
  useSearchParams: () => new URLSearchParams(searchStr),
}))

let searchStr = ''

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const searchMock = vi.fn(async (..._args: unknown[]) => ({
  galleries: [],
  total: 0,
  page: 0,
  next_gid: null,
}))
const autocompleteMock = vi.fn(async (..._args: unknown[]) => [
  { id: 1, namespace: 'female', name: 'big breasts', count: 42 },
])

vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: (...args: unknown[]) => searchMock(...args),
      getFavorites: vi.fn(),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
      getBrowseStatus: vi.fn(async () => ({ statuses: {} })),
    },
    tags: { autocomplete: (...args: unknown[]) => autocompleteMock(...args) },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
    history: { recordBrowse: vi.fn().mockResolvedValue({}) },
  },
}))

import BrowsePage from '@/app/e-hentai/page'

const SUGGESTION = 'big breasts'

function searchInput(): HTMLInputElement {
  return screen.getByPlaceholderText('browse.searchPlaceholder') as HTMLInputElement
}

async function typeAndWaitForSuggestion(value: string) {
  fireEvent.change(searchInput(), { target: { value } })
  expect(await screen.findByText(SUGGESTION)).toBeDefined()
}

// pointerdown, not mousedown: iOS only synthesizes mouse events for taps that
// land on a clickable element, so a tap on empty page area never fires one.
function pointerDownOutside() {
  fireEvent.pointerDown(document.body)
}

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'list')
  searchStr = ''
  window.history.replaceState({}, '', '/e-hentai')
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('E-Hentai search suggestion dropdown dismissal', () => {
  it('closes when the pointer goes down outside the search box', async () => {
    render(<BrowsePage />)
    await typeAndWaitForSuggestion('fem')

    pointerDownOutside()

    await waitFor(() => expect(screen.queryByText(SUGGESTION)).toBeNull())
    // The typed text is untouched — only the overlay goes away.
    expect(searchInput().value).toBe('fem')
  })

  it('closes on Escape', async () => {
    render(<BrowsePage />)
    await typeAndWaitForSuggestion('fem')

    fireEvent.keyDown(searchInput(), { key: 'Escape' })

    await waitFor(() => expect(screen.queryByText(SUGGESTION)).toBeNull())
  })

  it('closes when Enter submits the typed query', async () => {
    render(<BrowsePage />)
    await typeAndWaitForSuggestion('fem')

    fireEvent.keyDown(searchInput(), { key: 'Enter' })

    await waitFor(() => expect(screen.queryByText(SUGGESTION)).toBeNull())
  })

  it('closes after a suggestion is picked instead of re-listing the same tags', async () => {
    render(<BrowsePage />)
    await typeAndWaitForSuggestion('fem')

    fireEvent.mouseDown(screen.getByText(SUGGESTION))

    await waitFor(() => expect(searchInput().value).toBe('female:"big breasts$" '))
    await waitFor(() => expect(screen.queryByText(SUGGESTION)).toBeNull())
  })

  it('stays closed on mount when the query came from the URL', async () => {
    searchStr = 'q=fem'
    window.history.replaceState({}, '', '/e-hentai?q=fem')

    render(<BrowsePage />)
    await waitFor(() => expect(searchInput().value).toBe('fem'))
    await waitFor(() => expect(searchMock).toHaveBeenCalled())

    expect(screen.queryByText(SUGGESTION)).toBeNull()
    expect(autocompleteMock).not.toHaveBeenCalled()
  })

  it('reopens once the user types again after dismissing', async () => {
    render(<BrowsePage />)
    await typeAndWaitForSuggestion('fem')
    fireEvent.keyDown(searchInput(), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByText(SUGGESTION)).toBeNull())

    await typeAndWaitForSuggestion('fema')
  })
})

describe('E-Hentai search input debounce', () => {
  // Committing a query writes it to the URL, which is what seeds the upstream
  // E-Hentai request — so the URL is the earliest observable "sent" signal.
  it('does not commit the typed query until 1500ms of idle', async () => {
    render(<BrowsePage />)
    await screen.findByPlaceholderText('browse.searchPlaceholder')

    vi.useFakeTimers()
    fireEvent.change(searchInput(), { target: { value: 'slowquery' } })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1499)
    })
    expect(window.location.search).not.toContain('slowquery')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(window.location.search).toContain('slowquery')
  })

  it('restarts the idle window on every keystroke', async () => {
    render(<BrowsePage />)
    await screen.findByPlaceholderText('browse.searchPlaceholder')

    vi.useFakeTimers()
    fireEvent.change(searchInput(), { target: { value: 'slow' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    fireEvent.change(searchInput(), { target: { value: 'slowquery' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(window.location.search).toBe('')
  })
})
