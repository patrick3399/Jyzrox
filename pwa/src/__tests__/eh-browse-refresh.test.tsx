/**
 * The E-Hentai list can be refreshed on demand. A restored snapshot used to be
 * shown as-is for the life of the tab with no way to reload it; the refresh
 * reloads only the first page (one request — E-Hentai can IP-ban).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(),
      getFavorites: vi.fn(),
      getPopular: vi.fn(),
      getToplist: vi.fn(),
      getBrowseStatus: vi.fn(async () => ({ statuses: {} })),
    },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
  },
}))

import Page from '@/app/e-hentai/page'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { ehIdentityKey } from '@/lib/browse/ehentai'
import { initialFilters } from '@/lib/ehBrowseState'
import { createBrowseSnapshotStore } from '@/lib/browse/snapshotStore'

const gallery = (gid: number, title: string) =>
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

const TAB_ID = 'tab-eh-refresh'

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'list')
  vi.clearAllMocks()
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('E-Hentai list refresh', () => {
  it('the Refresh button reloads a restored list with one first-page request', async () => {
    sessionStorage.setItem('browse_session_tab_id_v1', TAB_ID)
    createBrowseSnapshotStore({
      storage: sessionStorage,
      scope: { userId: 'qa-user', tabId: TAB_ID, sourceId: 'ehentai', schemaVersion: 1 },
    }).save(ehIdentityKey({ tab: 'popular', query: '', filters: initialFilters }), {
      pages: [[gallery(1, 'Alpha'), gallery(2, 'Beta')]],
      cursor: null,
      hasMore: false,
      total: 2,
      anchor: null,
      layout: null,
    })
    ;(api.eh.getPopular as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [gallery(7, 'Fresh')],
      total: 1,
      page: 0,
    })

    render(<Page />)
    expect(await screen.findByText('Alpha')).toBeInTheDocument()
    expect(api.eh.getPopular).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: t('common.refresh') }))

    expect(await screen.findByText('Fresh')).toBeInTheDocument()
    expect(api.eh.getPopular).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Alpha')).toBeNull()
  })
})
