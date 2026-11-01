import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The root Pixiv page against the REAL browse session: tab-scope claim, snapshot
 * store and sessionStorage. Every remount (artwork -> back, tab switch) first
 * waits out the browse-tab claim, and the buffer is empty for that whole window
 * because nothing has been restored yet — it must read as "loading", not as
 * "No results".
 */

const h = vi.hoisted(() => ({
  feed: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams('tab=feed'),
}))
vi.mock('swr', () => ({
  default: () => ({ data: { pixiv: { configured: true } }, isLoading: false }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'alice' }, isLoading: false }),
}))
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/hooks/useIllustActions', () => ({
  useIllustActions: () => ({
    downloading: false,
    bookmarked: false,
    bookmarking: false,
    handleDownload: vi.fn(),
    handleBookmark: vi.fn(),
  }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: {
    items: Array<{ kind: string }>
    renderItem: (item: { kind: string }, index: number) => React.ReactNode
  }) => (
    <div data-testid="grid">
      {props.items.map((item, index) => (
        <div key={index}>{props.renderItem(item, index)}</div>
      ))}
    </div>
  ),
}))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/lib/ws', () => ({ useWsJobs: () => ({ lastJobUpdate: null }) }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getCredentials: vi.fn() },
    pixiv: {
      getFollowingFeed: (...args: unknown[]) => h.feed(...args),
      imageProxyUrl: (url: string) => url,
      followUser: vi.fn(),
      unfollowUser: vi.fn(),
    },
  },
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import PixivPage from '@/app/pixiv/page'

function illust(id: number) {
  return {
    id,
    title: `Illust ${id}`,
    image_urls: { square_medium: `/sq-${id}.jpg` },
    user: { id: 9, name: 'Artist' },
    tags: [],
    page_count: 1,
    total_view: 1,
    total_bookmarks: 1,
    is_bookmarked: false,
  }
}

/** Records whether "No results" was ever in the DOM at a task boundary, i.e. in a
 *  frame the user could have seen (a layout effect's synchronous re-render
 *  happens before any observer callback, as it does before paint). */
function watchForNoResults() {
  const watch = {
    seen: false,
    check() {
      if (document.body.textContent?.includes('pixiv.noResults')) watch.seen = true
    },
  }
  const observer = new MutationObserver(() => watch.check())
  observer.observe(document.body, { childList: true, subtree: true, characterData: true })
  stopWatching = () => observer.disconnect()
  return watch
}

let stopWatching = () => {}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  h.feed.mockResolvedValue({ illusts: [illust(1), illust(2)], next_offset: 30 })
})

afterEach(() => {
  stopWatching()
  vi.restoreAllMocks()
})

describe('root Pixiv page — remount against the real browse session', () => {
  it('shows the spinner, never "No results", while the first load waits out the tab claim', async () => {
    const watch = watchForNoResults()

    render(<PixivPage />)
    watch.check()

    expect(screen.getByTestId('spinner')).toBeInTheDocument()
    await screen.findByText('Illust 1')
    watch.check()
    expect(watch.seen).toBe(false)
  })

  it('renders the stored list on remount without a "No results" frame or a refetch', async () => {
    const first = render(<PixivPage />)
    await screen.findByText('Illust 2')
    first.unmount()
    expect(h.feed).toHaveBeenCalledTimes(1)
    const watch = watchForNoResults()

    render(<PixivPage />)
    watch.check()

    // The remount's first frame is inside the tab-claim window.
    expect(screen.getByTestId('spinner')).toBeInTheDocument()
    expect(screen.queryByText('Illust 1')).toBeNull()

    await screen.findByText('Illust 1')
    expect(screen.getByText('Illust 2')).toBeInTheDocument()
    watch.check()
    expect(watch.seen).toBe(false)
    expect(h.feed).toHaveBeenCalledTimes(1)
  })

  it('keeps the spinner up while the request that follows the claim is in flight', async () => {
    let resolve!: (value: unknown) => void
    h.feed.mockReturnValue(new Promise((r) => (resolve = r)))
    const watch = watchForNoResults()

    render(<PixivPage />)
    await waitFor(() => expect(h.feed).toHaveBeenCalledTimes(1))
    watch.check()
    expect(screen.getByTestId('spinner')).toBeInTheDocument()

    await act(async () => resolve({ illusts: [illust(5)], next_offset: null }))
    await screen.findByText('Illust 5')
    watch.check()
    expect(watch.seen).toBe(false)
  })

  it('still reports "No results" once a load really comes back empty', async () => {
    h.feed.mockResolvedValue({ illusts: [], next_offset: null })

    render(<PixivPage />)

    expect(await screen.findByText('pixiv.noResults')).toBeInTheDocument()
    expect(screen.queryByTestId('spinner')).toBeNull()
  })
})
