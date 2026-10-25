import { Suspense } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import IllustDetailPage from '@/app/pixiv/illust/[id]/page'
import { markTabRestore, rememberLocation } from '@/lib/navMemory'

/**
 * The Pixiv artwork page binds window-level keyboard shortcuts (Enter/Space
 * open the reader, Escape/ArrowUp go back) and renders the back FAB. It also
 * has loading / invalid / error states that render before the FAB would.
 */

const h = vi.hoisted(() => ({
  router: { back: vi.fn(), push: vi.fn(), replace: vi.fn() },
  api: {
    getIllust: vi.fn(),
    getBookmarkStatus: vi.fn(),
    addBookmark: vi.fn(),
    deleteBookmark: vi.fn(),
    enqueue: vi.fn(),
  },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => h.router,
  usePathname: () => '/pixiv/illust/118801677',
}))
vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => undefined }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))
vi.mock('@/components/TagSearchPopover', () => ({
  TagSearchPopover: ({ tag }: { tag: string }) => <div data-testid="tag-popover">{tag}</div>,
}))
vi.mock('@/lib/api', () => ({
  api: {
    pixiv: {
      getIllust: (...args: unknown[]) => h.api.getIllust(...args),
      getBookmarkStatus: (...args: unknown[]) => h.api.getBookmarkStatus(...args),
      addBookmark: (...args: unknown[]) => h.api.addBookmark(...args),
      deleteBookmark: (...args: unknown[]) => h.api.deleteBookmark(...args),
      imageProxyUrl: (url: string) => url,
    },
    download: { enqueue: (...args: unknown[]) => h.api.enqueue(...args) },
  },
}))

const ILLUST_ID = 118801677
const ILLUST_URL = `/pixiv/illust/${ILLUST_ID}`
const ROOTS = ['/pixiv']

const ILLUST = {
  id: ILLUST_ID,
  title: 'Artwork title',
  type: 'illust',
  image_urls: { square_medium: '/sq.jpg', medium: '/m.jpg', large: '/l.jpg' },
  caption: '',
  user: { id: 13419413, name: 'Artist', account: 'artist', profile_image: '/p.jpg' },
  tags: [{ name: 'blue', translated_name: null }],
  create_date: '2024-01-01T00:00:00+09:00',
  page_count: 1,
  width: 1,
  height: 1,
  sanity_level: 2,
  total_view: 10,
  total_bookmarks: 5,
  is_bookmarked: false,
}

function stubHistoryLength(length: number) {
  vi.spyOn(window.history, 'length', 'get').mockReturnValue(length)
}

async function renderPage(id = String(ILLUST_ID)) {
  await act(async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <Suspense>
          <IllustDetailPage params={Promise.resolve({ id })} />
        </Suspense>
      </SWRConfig>,
    )
  })
}

async function renderLoaded() {
  await renderPage()
  await screen.findByText('Artwork title')
}

function pressEscape(target: Element = document.body) {
  return fireEvent.keyDown(target, { key: 'Escape' })
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  window.history.replaceState({}, '', ILLUST_URL)
  h.api.getIllust.mockResolvedValue(ILLUST)
  h.api.getBookmarkStatus.mockResolvedValue({ is_bookmarked: false })
  h.api.enqueue.mockResolvedValue({})
  stubHistoryLength(3)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Pixiv artwork page — a way out in every state', () => {
  it('shows the fixed back FAB while the artwork is still loading', async () => {
    h.api.getIllust.mockReturnValue(new Promise(() => {}))

    await renderPage()

    const back = screen.getByRole('button', { name: 'common.back' })
    expect(back.className).toContain('fixed')
  })

  it('shows the fixed back FAB when the artwork id is not a number', async () => {
    await renderPage('not-a-number')

    expect(screen.getByText('common.invalidId')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'common.back' }).className).toContain('fixed')
  })

  it('error-state back climbs to the list after a tab restore instead of bare history back', async () => {
    h.api.getIllust.mockRejectedValue(new Error('boom'))
    rememberLocation(ROOTS, '/pixiv', 'tab=bookmarks')
    markTabRestore(ILLUST_URL)

    await renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /pixiv\.title/ }))

    expect(h.router.replace).toHaveBeenCalledWith('/pixiv?tab=bookmarks')
    expect(h.router.back).not.toHaveBeenCalled()
  })

  it('error-state back pushes /pixiv when the page is the only history entry', async () => {
    h.api.getIllust.mockRejectedValue(new Error('boom'))
    stubHistoryLength(1)

    await renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /pixiv\.title/ }))

    expect(h.router.push).toHaveBeenCalledWith('/pixiv')
    expect(h.router.back).not.toHaveBeenCalled()
  })
})

describe('Pixiv artwork page — page-level keyboard shortcuts', () => {
  it('Enter on the focused Download button downloads and does not open the reader', async () => {
    const user = userEvent.setup()
    await renderLoaded()

    screen.getByRole('button', { name: 'pixiv.download' }).focus()
    await user.keyboard('{Enter}')

    expect(h.api.enqueue).toHaveBeenCalledWith(`https://www.pixiv.net/artworks/${ILLUST_ID}`)
    expect(h.router.push).not.toHaveBeenCalled()
  })

  it('Enter on the focused back FAB is left to the FAB and does not open the reader', async () => {
    await renderLoaded()

    const notPrevented = fireEvent.keyDown(screen.getByRole('button', { name: 'common.back' }), {
      key: 'Enter',
    })

    expect(notPrevented).toBe(true)
    expect(h.router.push).not.toHaveBeenCalled()
  })

  it('Enter on the focused artist link is left to the link and does not open the reader', async () => {
    await renderLoaded()

    const notPrevented = fireEvent.keyDown(screen.getByRole('link', { name: /Artist/ }), {
      key: 'Enter',
    })

    expect(notPrevented).toBe(true)
    expect(h.router.push).not.toHaveBeenCalled()
  })

  it('Enter with nothing focused still opens the reader', async () => {
    await renderLoaded()

    fireEvent.keyDown(document.body, { key: 'Enter' })

    expect(h.router.push).toHaveBeenCalledWith(`/reader/pixiv/${ILLUST_ID}`)
  })

  it('Escape with the tag popover open closes nothing on the page and does not navigate', async () => {
    await renderLoaded()
    fireEvent.click(screen.getByRole('button', { name: /blue/ }))
    expect(screen.getByTestId('tag-popover')).toBeInTheDocument()

    pressEscape()
    fireEvent.keyDown(document.body, { key: 'ArrowUp' })

    expect(h.router.back).not.toHaveBeenCalled()
    expect(h.router.push).not.toHaveBeenCalled()
    expect(h.router.replace).not.toHaveBeenCalled()
  })

  it('Escape after a tab restore climbs to the remembered list instead of history back', async () => {
    rememberLocation(ROOTS, '/pixiv', 'tab=bookmarks')
    markTabRestore(ILLUST_URL)
    await renderLoaded()

    pressEscape()

    expect(h.router.replace).toHaveBeenCalledWith('/pixiv?tab=bookmarks')
    expect(h.router.back).not.toHaveBeenCalled()
  })

  it('Escape goes back through history when there is somewhere to go back to', async () => {
    await renderLoaded()

    pressEscape()

    expect(h.router.back).toHaveBeenCalledTimes(1)
    expect(h.router.push).not.toHaveBeenCalled()
  })

  it('Escape pushes /pixiv when the page is the only history entry (share link)', async () => {
    stubHistoryLength(1)
    await renderLoaded()

    pressEscape()

    expect(h.router.push).toHaveBeenCalledWith('/pixiv')
    expect(h.router.back).not.toHaveBeenCalled()
  })

  it('Escape typed into a text field does not navigate', async () => {
    await renderLoaded()
    const input = document.createElement('input')
    document.body.appendChild(input)

    pressEscape(input)
    input.remove()

    expect(h.router.back).not.toHaveBeenCalled()
    expect(h.router.push).not.toHaveBeenCalled()
  })
})

describe('Pixiv artwork page — bookmark toggle label', () => {
  it('labels the toggle as add-bookmark when the artwork is not bookmarked', async () => {
    await renderLoaded()

    const toggle = screen.getByRole('button', { name: 'pixiv.addBookmark' })
    expect(toggle).toHaveAttribute('title', 'pixiv.addBookmark')
  })

  it('labels the toggle as remove-bookmark, not Unfollow, when the artwork is bookmarked', async () => {
    h.api.getBookmarkStatus.mockResolvedValue({ is_bookmarked: true })
    await renderLoaded()

    const toggle = await screen.findByRole('button', { name: 'pixiv.removeBookmark' })
    expect(toggle).toHaveAttribute('title', 'pixiv.removeBookmark')
    expect(screen.queryByTitle('pixiv.unfollow')).toBeNull()
  })
})
