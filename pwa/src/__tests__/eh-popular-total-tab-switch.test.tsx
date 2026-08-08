import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

const popularGallery = vi.hoisted(() => ({
  gid: 777,
  token: 'popular-token',
  title: 'Popular Gallery',
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
      search: vi.fn(async () => ({ galleries: [], total: 0, next_gid: null })),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [],
      })),
      // The popular page has no result counter. Before the fix the backend
      // shipped this payload with no `total` at all.
      getPopular: vi.fn(async () => ({ galleries: [popularGallery] })),
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

describe('E-Hentai results header with a source payload that omits total', () => {
  it('switching from popular to the latest tab renders instead of dereferencing an undefined total', async () => {
    // Regression: the Latest tab section renders one frame against the
    // previous identity's buffer, before the session's layout effect resets
    // state for the new identity. With popular's total left undefined, the
    // `total !== null` guard let that frame reach total.toLocaleString().
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Popular Gallery')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'browse.latestTab' }))

    expect(screen.getByPlaceholderText('browse.searchPlaceholder')).toBeInTheDocument()
    expect(screen.queryByText('browse.resultsCount')).not.toBeInTheDocument()
  })

  it('keeps the popular header out of the DOM while total is unknown', async () => {
    render(<Page />)
    await waitFor(() => expect(screen.getByText('Popular Gallery')).toBeInTheDocument())

    expect(screen.queryByText(/browse\.results$/)).not.toBeInTheDocument()
  })
})
