import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

let searchStr = ''
const push = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [],
      })),
      getPopular: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
    },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
  },
}))

import Page from '@/app/e-hentai/page'
import { api } from '@/lib/api'
import { serializeSnapshot, reducer, initialState } from '@/lib/ehBrowseState'

const g = (gid: number, title: string) =>
  ({
    gid,
    token: `t${gid}`,
    title,
    title_jpn: '',
    category: 'manga',
    thumb: '',
    uploader: 'u',
    posted_at: 0,
    pages: 1,
    rating: 0,
    tags: [],
    expunged: false,
  }) as never

beforeEach(() => {
  searchStr = ''
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'list') // deterministic rendering (no VirtualGrid virtualization)
  vi.clearAllMocks()
})

describe('e-hentai back-nav restores the scroll buffer', () => {
  it('restores accumulated buffer without re-fetching, first item unshifted', async () => {
    searchStr = 'tab=search&q=foo'
    let s = reducer(initialState, { type: 'SET_TAB', tab: 'search' })
    s = reducer(s, { type: 'COMMIT_QUERY', query: 'foo' })
    s = reducer(s, {
      type: 'SEED',
      items: [g(1, 'One'), g(2, 'Two')],
      total: 2,
      cursor: { kind: 'gid', nextGid: 7 },
      hasMore: true,
    })
    sessionStorage.setItem('eh_browse_snapshot', serializeSnapshot(s))

    render(<Page />)
    await waitFor(() => expect(screen.getByText('One')).toBeInTheDocument())
    expect(screen.getByText('Two')).toBeInTheDocument()
    // Buffer restored → no seed fetch fired, first item not shifted.
    expect(api.eh.search).not.toHaveBeenCalled()
  })
})

describe('e-hentai search input', () => {
  it('committing a query triggers a seed fetch', async () => {
    ;(api.eh.search as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [g(3, 'Hit')],
      total: 1,
      page: 0,
      next_gid: null,
    })
    render(<Page />)
    const inputs = screen.getAllByPlaceholderText(/search/i)
    const input = inputs[inputs.length - 1]
    fireEvent.change(input, { target: { value: 'hello' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getByText('Hit')).toBeInTheDocument())
    expect(api.eh.search).toHaveBeenCalledWith(
      expect.objectContaining({ q: 'hello' }),
      expect.anything(),
    )
  })
})
