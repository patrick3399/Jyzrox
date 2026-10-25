import { Suspense } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import UserProfilePage from '@/app/pixiv/user/[id]/page'
import { markTabRestore, rememberLocation } from '@/lib/navMemory'

/**
 * The Pixiv artist page: back control, sub-tab (works / bookmarks) kept in the
 * URL, bookmarks paginated by the server's cursor, and the scroll position kept
 * across artist -> artwork -> back.
 */

const h = vi.hoisted(() => ({
  router: { back: vi.fn(), push: vi.fn(), replace: vi.fn() },
  search: '',
  api: {
    getUser: vi.fn(),
    getUserCollection: vi.fn(),
    getUserIllusts: vi.fn(),
    getUserBookmarks: vi.fn(),
  },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => h.router,
  usePathname: () => '/pixiv/user/13419413',
  useSearchParams: () => new URLSearchParams(h.search),
}))
vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => undefined }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/lib/api', () => ({
  api: {
    pixiv: {
      getUser: (...args: unknown[]) => h.api.getUser(...args),
      getUserCollection: (...args: unknown[]) => h.api.getUserCollection(...args),
      getUserIllusts: (...args: unknown[]) => h.api.getUserIllusts(...args),
      getUserBookmarks: (...args: unknown[]) => h.api.getUserBookmarks(...args),
      imageProxyUrl: (url: string) => url,
      followUser: vi.fn(),
      unfollowUser: vi.fn(),
    },
    download: { enqueue: vi.fn() },
  },
}))

const USER_ID = 13419413
const USER_URL = `/pixiv/user/${USER_ID}`
const ROOTS = ['/pixiv']

function illust(id: number) {
  return {
    id,
    title: `Illust ${id}`,
    type: 'illust',
    image_urls: { square_medium: `/sq-${id}.jpg`, medium: '', large: '' },
    caption: '',
    user: { id: USER_ID, name: 'Artist', account: 'artist', profile_image: '/p.jpg' },
    tags: [],
    create_date: '2024-01-01T00:00:00+09:00',
    page_count: 1,
    width: 1,
    height: 1,
    sanity_level: 2,
    total_view: 1,
    total_bookmarks: 1,
    is_bookmarked: false,
  }
}

const USER_RESULT = {
  user: {
    id: USER_ID,
    name: 'Artist Name',
    account: 'artist',
    profile_image: '/avatar.jpg',
    comment: '',
    total_illusts: 3,
    total_manga: 0,
    total_novels: 0,
    is_followed: false,
  },
  recent_illusts: [] as ReturnType<typeof illust>[],
  next_offset: null,
}

function stubHistoryLength(length: number) {
  vi.spyOn(window.history, 'length', 'get').mockReturnValue(length)
}

function tree(cache: Map<string, unknown>, id: string) {
  return (
    <SWRConfig value={{ provider: () => cache as never, dedupingInterval: 0 }}>
      <Suspense>
        <UserProfilePage params={Promise.resolve({ id })} />
      </Suspense>
    </SWRConfig>
  )
}

async function renderPage(cache = new Map<string, unknown>(), id = String(USER_ID)) {
  let view!: ReturnType<typeof render>
  await act(async () => {
    view = render(tree(cache, id))
  })
  return { ...view, cache }
}

async function renderLoaded(cache = new Map<string, unknown>()) {
  const view = await renderPage(cache)
  await screen.findByText('Artist Name')
  return view
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  h.search = ''
  window.history.replaceState({}, '', USER_URL)
  stubHistoryLength(3)
  h.api.getUser.mockResolvedValue(USER_RESULT)
  h.api.getUserCollection.mockResolvedValue({
    gallery_id: null,
    gallery_source_id: null,
    subscribed: false,
    subscription_id: null,
    job_id: null,
    job_status: null,
    work_count: 0,
    missing_count: 0,
  })
  h.api.getUserIllusts.mockResolvedValue({ illusts: [illust(1), illust(2)], next_offset: null })
  h.api.getUserBookmarks.mockResolvedValue({
    illusts: [illust(501), illust(502)],
    next_offset: null,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Pixiv artist page — back control', () => {
  it('uses the fixed back FAB and has no inline top-left back button', async () => {
    await renderLoaded()

    const back = screen.getByRole('button', { name: 'common.back' })
    expect(back.className).toContain('fixed')
    expect(screen.queryByRole('button', { name: /pixiv\.title/ })).toBeNull()
  })

  it('shows the fixed back FAB while the artist is still loading', async () => {
    h.api.getUser.mockReturnValue(new Promise(() => {}))

    await renderPage()

    expect(screen.getByRole('button', { name: 'common.back' }).className).toContain('fixed')
  })

  it('shows the fixed back FAB when the artist id is not a number', async () => {
    await renderPage(new Map(), 'nope')

    expect(screen.getByText('common.invalidId')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'common.back' }).className).toContain('fixed')
  })

  it('pushes /pixiv when the artist page is the only history entry (share link)', async () => {
    stubHistoryLength(1)
    await renderLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'common.back' }))

    expect(h.router.push).toHaveBeenCalledWith('/pixiv')
    expect(h.router.back).not.toHaveBeenCalled()
  })

  it('climbs to the remembered list after a tab restore instead of bare history back', async () => {
    rememberLocation(ROOTS, '/pixiv', 'tab=bookmarks')
    markTabRestore(USER_URL)
    await renderLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'common.back' }))

    expect(h.router.replace).toHaveBeenCalledWith('/pixiv?tab=bookmarks')
    expect(h.router.back).not.toHaveBeenCalled()
  })

  it('climbs to the remembered list after a tab restore onto the bookmarks sub-tab', async () => {
    h.search = 'tab=bookmarks'
    window.history.replaceState({}, '', `${USER_URL}?tab=bookmarks`)
    rememberLocation(ROOTS, '/pixiv', 'tab=feed')
    markTabRestore(`${USER_URL}?tab=bookmarks`)
    await renderLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'common.back' }))

    expect(h.router.replace).toHaveBeenCalledWith('/pixiv?tab=feed')
  })

  it('error-state back climbs after a tab restore instead of bare history back', async () => {
    h.api.getUser.mockRejectedValue(new Error('boom'))
    rememberLocation(ROOTS, '/pixiv', 'tab=bookmarks')
    markTabRestore(USER_URL)

    await renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /pixiv\.title/ }))

    expect(h.router.replace).toHaveBeenCalledWith('/pixiv?tab=bookmarks')
    expect(h.router.back).not.toHaveBeenCalled()
  })

  it('error-state back pushes /pixiv when the page is the only history entry', async () => {
    h.api.getUser.mockRejectedValue(new Error('boom'))
    stubHistoryLength(1)

    await renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /pixiv\.title/ }))

    expect(h.router.push).toHaveBeenCalledWith('/pixiv')
    expect(h.router.back).not.toHaveBeenCalled()
  })
})

describe('Pixiv artist page — sub-tab lives in the URL', () => {
  it('opens on the bookmarks tab when the URL says tab=bookmarks', async () => {
    h.search = 'tab=bookmarks'

    await renderLoaded()

    expect(screen.getByRole('button', { name: 'pixiv.userBookmarks' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('button', { name: 'pixiv.userWorks' })).not.toHaveAttribute(
      'aria-current',
    )
    expect(await screen.findByText('Illust 501')).toBeInTheDocument()
    expect(h.api.getUserBookmarks).toHaveBeenCalledWith(USER_ID, 0, expect.anything())
  })

  it('opens on the works tab without a tab param and does not fetch bookmarks', async () => {
    await renderLoaded()

    expect(screen.getByRole('button', { name: 'pixiv.userWorks' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(h.api.getUserBookmarks).not.toHaveBeenCalled()
  })

  it('switching tabs writes the URL through history.replaceState, not the router', async () => {
    const replaceState = vi.spyOn(window.history, 'replaceState')
    const pushState = vi.spyOn(window.history, 'pushState')
    const view = await renderLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'pixiv.userBookmarks' }))
    expect(replaceState).toHaveBeenLastCalledWith({}, '', `${USER_URL}?tab=bookmarks`)

    // The App Router's patched replaceState is what updates useSearchParams.
    h.search = 'tab=bookmarks'
    await act(async () => view.rerender(tree(view.cache, String(USER_ID))))
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.userWorks' }))
    expect(replaceState).toHaveBeenLastCalledWith({}, '', USER_URL)

    expect(pushState).not.toHaveBeenCalled()
    expect(h.router.push).not.toHaveBeenCalled()
    expect(h.router.replace).not.toHaveBeenCalled()
  })

  it('follows the URL when back/forward changes the tab on the mounted page', async () => {
    const view = await renderLoaded()
    expect(screen.getByRole('button', { name: 'pixiv.userWorks' })).toHaveAttribute(
      'aria-current',
      'page',
    )

    h.search = 'tab=bookmarks'
    await act(async () => {
      view.rerender(tree(view.cache, String(USER_ID)))
    })

    expect(screen.getByRole('button', { name: 'pixiv.userBookmarks' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})

describe('Pixiv artist page — bookmarks pagination uses the server cursor', () => {
  function twoPages() {
    h.search = 'tab=bookmarks'
    h.api.getUserBookmarks.mockImplementation(async (_id: number, offset: number) =>
      offset === 0
        ? { illusts: [illust(501), illust(502)], next_offset: 900 }
        : { illusts: [illust(503)], next_offset: null },
    )
  }

  it('Load more appends the next page and requests it with the previous next_offset', async () => {
    twoPages()
    await renderLoaded()
    await screen.findByText('Illust 501')

    fireEvent.click(screen.getByRole('button', { name: 'pixiv.loadMore' }))

    expect(await screen.findByText('Illust 503')).toBeInTheDocument()
    expect(screen.getByText('Illust 501')).toBeInTheDocument()
    expect(screen.getByText('Illust 502')).toBeInTheDocument()
    expect(h.api.getUserBookmarks).toHaveBeenCalledWith(USER_ID, 900, expect.anything())
    expect(screen.queryByRole('button', { name: 'pixiv.loadMore' })).toBeNull()
  })

  it('has no Previous page button: the cursor is an id, not an offset to subtract from', async () => {
    twoPages()
    await renderLoaded()
    await screen.findByText('Illust 501')

    fireEvent.click(screen.getByRole('button', { name: 'pixiv.loadMore' }))
    await screen.findByText('Illust 503')

    expect(screen.queryByRole('button', { name: 'common.previousPage' })).toBeNull()
  })

  it('keeps the loaded depth when the page is remounted from the SWR cache', async () => {
    twoPages()
    const cache = new Map<string, unknown>()
    const first = await renderLoaded(cache)
    await screen.findByText('Illust 501')
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.loadMore' }))
    await screen.findByText('Illust 503')
    first.unmount()
    const callsBefore = h.api.getUserBookmarks.mock.calls.length

    await renderPage(cache)

    // Synchronously from the cache: both pages are there on the first render.
    expect(screen.getByText('Illust 501')).toBeInTheDocument()
    expect(screen.getByText('Illust 503')).toBeInTheDocument()
    expect(h.api.getUserBookmarks.mock.calls.length).toBe(callsBefore)
  })

  it('shows the empty state only after the first bookmarks page came back empty', async () => {
    h.search = 'tab=bookmarks'
    let resolve!: (value: unknown) => void
    h.api.getUserBookmarks.mockReturnValue(new Promise((r) => (resolve = r)))
    await renderLoaded()

    expect(screen.queryByText('pixiv.noBookmarks')).toBeNull()

    await act(async () => resolve({ illusts: [], next_offset: null }))
    expect(await screen.findByText('pixiv.noBookmarks')).toBeInTheDocument()
  })
})

describe('Pixiv artist page — scroll position survives artist -> artwork -> back', () => {
  let scrollTo: ReturnType<typeof vi.spyOn>
  let preventNavigation: (event: Event) => void

  function setScrollY(value: number) {
    Object.defineProperty(window, 'scrollY', { configurable: true, value })
  }

  beforeEach(() => {
    scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    setScrollY(0)
    // jsdom cannot navigate; keep link clicks from logging "not implemented".
    preventNavigation = (event) => event.preventDefault()
    document.addEventListener('click', preventNavigation)
  })

  afterEach(() => {
    document.removeEventListener('click', preventNavigation)
    Reflect.deleteProperty(window, 'scrollY')
  })

  it('records the scroll position at the moment an artwork card is clicked', async () => {
    await renderLoaded()
    await screen.findByText('Illust 2')

    setScrollY(640)
    fireEvent.click(screen.getByText('Illust 2'))

    expect(sessionStorage.getItem(`pixiv_user_scroll:${USER_ID}:works`)).toBe('640')
  })

  it('restores the recorded position once the remounted page has its data, then forgets it', async () => {
    const cache = new Map<string, unknown>()
    const first = await renderLoaded(cache)
    await screen.findByText('Illust 2')
    setScrollY(640)
    fireEvent.click(screen.getByText('Illust 2'))
    first.unmount()
    setScrollY(0)

    await renderPage(cache)

    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 640))
    expect(sessionStorage.getItem(`pixiv_user_scroll:${USER_ID}:works`)).toBeNull()
  })

  it('does not scroll before the artist data has rendered', async () => {
    sessionStorage.setItem(`pixiv_user_scroll:${USER_ID}:works`, '640')
    h.api.getUser.mockReturnValue(new Promise(() => {}))

    await renderPage()
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30))
    })

    expect(scrollTo).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(`pixiv_user_scroll:${USER_ID}:works`)).toBe('640')
  })

  it('keeps works and bookmarks positions apart', async () => {
    h.search = 'tab=bookmarks'
    sessionStorage.setItem(`pixiv_user_scroll:${USER_ID}:works`, '900')
    sessionStorage.setItem(`pixiv_user_scroll:${USER_ID}:bookmarks`, '420')

    await renderLoaded()

    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 420))
    expect(scrollTo).not.toHaveBeenCalledWith(0, 900)
    expect(sessionStorage.getItem(`pixiv_user_scroll:${USER_ID}:works`)).toBe('900')
  })

  it('does not record anything when the click is on the Download button, not a link', async () => {
    await renderLoaded()
    await screen.findByText('Illust 2')

    setScrollY(640)
    fireEvent.click(screen.getAllByRole('button', { name: 'pixiv.download' })[0])

    expect(sessionStorage.getItem(`pixiv_user_scroll:${USER_ID}:works`)).toBeNull()
  })
})
