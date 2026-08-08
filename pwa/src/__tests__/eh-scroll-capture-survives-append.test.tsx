/**
 * The browse page captures a scroll position in a requestAnimationFrame. The
 * effect that owns the scroll listener also depended on `captureAnchor`, which
 * changes whenever `items` changes — so an append that committed before the
 * frame fired tore the effect down, cancelled the pending frame, and dropped
 * that scroll position without rescheduling it.
 *
 * Infinite scroll makes that window routine: scrolling is what triggers the
 * append. The observed trace was:
 *
 *   onScroll scheduled=true
 *   DETACH pendingFrame=true items=0
 *   ATTACH items=2
 *
 * `capture` never ran, so the live anchor kept scrollY 0, the snapshot banked 0,
 * and returning to the list restored to the top.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

let searchStr = ''
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(searchStr),
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
      getToplist: vi.fn(async () => ({ galleries: [], total: 0, page: 0 })),
    },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
  },
}))

import Page from '@/app/e-hentai/page'
import { api } from '@/lib/api'
import { snapshotStorageKey } from '@/lib/browse/snapshotStore'

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

function setScrollY(value: number) {
  Object.defineProperty(window, 'scrollY', { value, configurable: true, writable: true })
}

async function flushRaf() {
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
}

function bankedAnchor() {
  const tabId = sessionStorage.getItem('browse_session_tab_id_v1')
  if (!tabId) return undefined
  const raw = sessionStorage.getItem(
    snapshotStorageKey({ userId: 'qa-user', tabId, sourceId: 'ehentai', schemaVersion: 1 }),
  )
  if (!raw) return undefined
  const store = JSON.parse(raw) as {
    entries: Array<{
      identityKey: string
      snapshot: { anchor: { itemId: number | null; offset: number; scrollY: number } | null }
    }>
  }
  return store.entries.find((entry) => entry.identityKey.includes('"surface":"favorites"'))?.snapshot
    .anchor
}

beforeEach(() => {
  searchStr = ''
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem('eh_view_mode', 'list')
  vi.clearAllMocks()
  setScrollY(0)
})

describe('e-hentai scroll capture vs a concurrent append', () => {
  it('a scroll captured while a page is still in flight is not dropped when that page commits', async () => {
    searchStr = 'tab=favorites&favcat=3'

    // Hold the seed page open so the commit that changes `items` lands after the
    // scroll event has already scheduled its capture frame.
    let releaseSeed: () => void = () => {}
    const seed = new Promise<void>((resolve) => {
      releaseSeed = resolve
    })
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      await seed
      return {
        galleries: [g(1, 'Alpha'), g(2, 'Beta')],
        total: 2,
        has_next: true,
        next_cursor: 'A',
        categories: [],
      }
    })

    const view = render(<Page />)
    await waitFor(() => expect(api.eh.getFavorites).toHaveBeenCalledTimes(1))

    // Scroll while the list is still empty: this schedules the capture frame.
    setScrollY(5000)
    fireEvent.scroll(window)

    // Now let the page commit, which is what used to cancel that frame.
    releaseSeed()
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    await flushRaf()

    // Assert while still mounted: unmount banks the position through its own
    // path, which would mask a dropped capture. The settle timer is 250ms.
    await waitFor(() => expect(bankedAnchor()?.scrollY).toBe(5000), { timeout: 2000 })
    view.unmount()
  })
})
