import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let searchStr = ''
const replace = vi.fn()
const push = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push, back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))

vi.mock('@/hooks/useSubscriptions', () => ({
  useCreateSubscription: () => ({ trigger: vi.fn(), isMutating: false }),
  useSubscriptions: () => ({ data: { subscriptions: [] }, mutate: vi.fn() }),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))

vi.mock('swr', () => ({
  default: () => ({ data: { ehentai: { configured: true } }, isLoading: false }),
}))

vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: -1 }),
}))

vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: ({
    items,
    renderItem,
  }: {
    items: unknown[]
    renderItem: (item: unknown, index: number) => React.ReactNode
  }) => <div data-testid="grid">{items.map((item, index) => renderItem(item, index))}</div>,
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))

vi.mock('@/components/CredentialBanner', () => ({
  CredentialBanner: () => null,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

const gallery = vi.hoisted(() => ({
  gid: 314,
  token: 'checkpoint-token',
  title: 'Checkpoint Gallery',
  title_jpn: '',
  category: 'manga',
  thumb: '',
  uploader: 'uploader',
  posted_at: 0,
  pages: 1,
  rating: 4,
  tags: [],
  expunged: false,
}))

vi.mock('@/lib/api', () => ({
  api: {
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    tags: { autocomplete: vi.fn(async () => []) },
    eh: {
      search: vi.fn(async () => ({ galleries: [gallery], total: 1, next_gid: null })),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [],
      })),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0 })),
      getBrowseStatus: vi.fn(async () => ({ statuses: {} })),
    },
  },
}))

import Page from '@/app/e-hentai/page'

beforeEach(() => {
  searchStr = ''
  localStorage.clear()
  sessionStorage.clear()
  localStorage.setItem('eh_view_mode', 'list')
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('E-Hentai browse-session URL ownership', () => {
  it('uses same-document history for Latest and Toplists without invoking the Next router', async () => {
    // Tab switches push so the previous tab stays reachable by back, and they
    // pass a fresh state object so the App Router's history patch engages
    // instead of bailing out on the existing entry's `__NA`.
    const pushState = vi.spyOn(window.history, 'pushState')
    const view = render(<Page />)

    fireEvent.click(screen.getByRole('button', { name: 'browse.latestTab' }))
    expect(pushState).toHaveBeenLastCalledWith({}, '', '/e-hentai?tab=search')
    expect(replace).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'browse.toplistTab' }))
    expect(pushState).toHaveBeenLastCalledWith({}, '', '/e-hentai?tab=toplist')
    expect(replace).not.toHaveBeenCalled()

    view.unmount()
    pushState.mockRestore()
  })

  it('pending debounced input cannot overwrite a newer externally supplied URL identity', async () => {
    const view = render(<Page />)
    const input = screen.getByPlaceholderText('browse.searchPlaceholder')

    fireEvent.change(input, { target: { value: 'stale-debounce' } })

    searchStr = 'q=fresh-external'
    view.rerender(<Page />)
    await waitFor(() => expect(input).toHaveValue('fresh-external'))

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 650))
    })

    expect(input).toHaveValue('fresh-external')
    expect(replace).not.toHaveBeenCalledWith(
      expect.stringContaining('q=stale-debounce'),
      expect.anything(),
    )
  })
})

describe('E-Hentai browse-session navigation checkpoint', () => {
  it('checkpoints the active list synchronously before pointer navigation', async () => {
    searchStr = 'q=checkpoint'
    let snapshotAtPush: string | null = null
    push.mockImplementationOnce(() => {
      const scopedKey = Array.from({ length: sessionStorage.length }, (_, index) =>
        sessionStorage.key(index),
      ).find((key) => key?.startsWith('browse_session_v1:qa-user:'))
      snapshotAtPush = scopedKey ? sessionStorage.getItem(scopedKey) : null
    })

    render(<Page />)
    await waitFor(() => expect(screen.getByText('Checkpoint Gallery')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Checkpoint Gallery'))

    expect(push).toHaveBeenCalledWith('/e-hentai/314/checkpoint-token')
    expect(snapshotAtPush).not.toBeNull()
    const stored = JSON.parse(snapshotAtPush ?? '{}') as {
      entries?: { snapshot?: { pages?: { gid: number }[][] } }[]
    }
    expect(stored.entries?.[0]?.snapshot?.pages?.flat().map((item) => item.gid)).toContain(314)
  })

  it('does not serialize the full browse session on every animation-frame scroll capture', async () => {
    searchStr = 'q=checkpoint'
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Checkpoint Gallery')).toBeInTheDocument())

    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    fireEvent.scroll(window)
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve))
    })

    expect(
      setItem.mock.calls.filter(([key]) =>
        String(key).startsWith('browse_session_v1:'),
      ),
    ).toHaveLength(0)
    expect(setItem.mock.calls.filter(([key]) => key === 'eh_browse_snapshot')).toHaveLength(0)
    setItem.mockRestore()
  })
})

describe('E-Hentai expired image-search recovery', () => {
  it('renders a localized, actionable recovery alert for an expired upload session', async () => {
    searchStr = 'image_session=missing-upload'
    render(<Page />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('error.session_expired')
    expect(alert).toHaveRole('alert')
    expect(alert.querySelector('button')).not.toBeNull()
  })
})
