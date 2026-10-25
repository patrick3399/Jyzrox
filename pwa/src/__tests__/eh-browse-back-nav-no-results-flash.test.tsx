/**
 * Regression (audit EH-2): back-navigating to the E-Hentai list flashed
 * "No results" before the saved snapshot appeared.
 *
 * Every remount waits for the browse-tab-scope claim (a >= 32 ms broadcast
 * probe) before the session kernel can restore. During that window the kernel
 * published an idle, empty buffer, so the page rendered its empty state; the
 * seed effect could also fire a fetch against the placeholder scope. This
 * renders the real page, hook and kernel (only the network is stubbed).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'

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
      getPopular: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
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

const TAB_ID = 'tab-back-nav'

function seedPopularSnapshot() {
  sessionStorage.setItem('browse_session_tab_id_v1', TAB_ID)
  const store = createBrowseSnapshotStore({
    storage: sessionStorage,
    scope: { userId: 'qa-user', tabId: TAB_ID, sourceId: 'ehentai', schemaVersion: 1 },
  })
  const saved = store.save(ehIdentityKey({ tab: 'popular', query: '', filters: initialFilters }), {
    pages: [[gallery(1, 'Alpha'), gallery(2, 'Beta')]],
    cursor: null,
    hasMore: false,
    total: 2,
    anchor: null,
    layout: null,
  })
  expect(saved).toBe(true)
}

describe('E-Hentai list while the browse-tab scope claim is pending', () => {
  let observer: MutationObserver | undefined

  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    localStorage.setItem('eh_view_mode', 'list')
    vi.clearAllMocks()
  })

  afterEach(() => {
    observer?.disconnect()
    observer = undefined
  })

  it('shows loading, never "No results", between mount and snapshot hydration', async () => {
    seedPopularSnapshot()
    const noResults = t('browse.noResults')
    let everShowedNoResults = false
    observer = new MutationObserver(() => {
      if (document.body.textContent?.includes(noResults)) everShowedNoResults = true
    })
    observer.observe(document.body, { childList: true, subtree: true, characterData: true })

    render(<Page />)

    // Before the claim resolves: the list is unresolved, not empty.
    expect(screen.queryByText(noResults)).toBeNull()
    expect(screen.getByRole('status', { name: t('common.loading') })).toBeInTheDocument()

    // After the claim the saved snapshot hydrates, with no request issued.
    expect(await screen.findByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
    expect(everShowedNoResults).toBe(false)
    expect(api.eh.getPopular).not.toHaveBeenCalled()
  })

  it('fetches the first page once the scope is ready when there is no snapshot', async () => {
    sessionStorage.setItem('browse_session_tab_id_v1', TAB_ID)
    ;(api.eh.getPopular as ReturnType<typeof vi.fn>).mockResolvedValue({
      galleries: [gallery(7, 'Fresh')],
      total: 1,
      page: 0,
    })

    render(<Page />)

    expect(screen.queryByText(t('browse.noResults'))).toBeNull()
    expect(await screen.findByText('Fresh')).toBeInTheDocument()
    expect(api.eh.getPopular).toHaveBeenCalledTimes(1)
  })
})
