import fs from 'node:fs'
import path from 'node:path'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

type SessionItem =
  | { kind: 'illust'; illust: Record<string, unknown> }
  | { kind: 'user'; preview: Record<string, unknown> }

type GridProps = {
  items: SessionItem[]
  columns: Record<string, number>
  renderItem: (item: SessionItem) => React.ReactNode
  onRegisterElement?: (index: number, element: HTMLElement | null) => void
  onLayoutChange?: (layout: {
    colCount: number
    containerWidth: number
    scrollMargin: number
  }) => void
  restoreRequest?: { key: string; index: number }
  onRestoreApplied?: (request: { key: string; index: number }) => void
}

const testState = vi.hoisted(() => {
  const checkpoint = vi.fn()
  const loadMore = vi.fn()
  const refresh = vi.fn(async () => undefined)
  const retry = vi.fn(async () => undefined)
  const replacePage = vi.fn()
  const updateView = vi.fn()
  const acknowledgeRestore = vi.fn()
  return {
    push: vi.fn(),
    replace: vi.fn(),
    checkpoint,
    loadMore,
    refresh,
    retry,
    replacePage,
    updateView,
    acknowledgeRestore,
    search: '',
    gridProps: undefined as GridProps | undefined,
    gridHistory: [] as GridProps[],
    session: {
      state: {
        items: [] as SessionItem[],
        pages: [] as SessionItem[][],
        cursor: null as { kind: 'offset'; value: number } | null,
        hasMore: false,
        total: null as number | null,
        meta: undefined,
        identityKey: 'pixiv:a',
        generation: 1,
        status: 'ready',
        error: null as Error | null,
      },
      checkpoint,
      loadMore,
      refresh,
      retry,
      replacePage,
      updateView,
      acknowledgeRestore,
      restoreInstruction: null as null | {
        key: string
        identityKey: string
        target:
          | { kind: 'top' }
          | {
              kind: 'view'
              view: {
                anchor: { itemId: string | null; offset: number; scrollY: number } | null
                layout: { columns: number; width: number; mode: string } | null
              }
            }
      },
    },
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: testState.push, replace: testState.replace }),
  useSearchParams: () => new URLSearchParams(testState.search),
}))
vi.mock('swr', () => ({
  default: () => ({ data: { pixiv: { configured: true } }, isLoading: false }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'alice' }, isLoading: false }),
}))
vi.mock('@/hooks/usePixivBrowseSession', () => ({
  usePixivBrowseSession: () => testState.session,
}))
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/hooks/useIllustActions', () => ({
  useIllustActions: (
    _illust: Record<string, unknown>,
    onBookmark: (bookmarked: boolean) => void,
  ) => ({
    downloading: false,
    bookmarked: false,
    bookmarking: false,
    handleDownload: vi.fn(),
    handleBookmark: () => onBookmark(true),
  }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: GridProps) => {
    testState.gridProps = props
    testState.gridHistory.push(props)
    return (
      <div data-testid="grid">
        {props.items.map((item, index) => (
          <div
            key={index}
            ref={(element) => props.onRegisterElement?.(index, element)}
            data-testid={`grid-item-${index}`}
          >
            {props.renderItem(item)}
          </div>
        ))}
      </div>
    )
  },
}))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getCredentials: vi.fn() },
    pixiv: {
      imageProxyUrl: (url: string) => url,
      followUser: vi.fn(async () => undefined),
      unfollowUser: vi.fn(async () => undefined),
    },
  },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import PixivPage from '@/app/pixiv/page'

const pageSource = fs.readFileSync(path.resolve(process.cwd(), 'src/app/pixiv/page.tsx'), 'utf8')
const sessionSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/hooks/useBrowseSession.ts'),
  'utf8',
)

function illust(id: number): SessionItem {
  return {
    kind: 'illust',
    illust: {
      id,
      title: `illust-${id}`,
      image_urls: { square_medium: `/image-${id}.jpg` },
      user: { id: id + 100, name: `user-${id}` },
      tags: [{ name: 'tag-one' }, { name: 'tag-two' }],
      page_count: 1,
      total_view: 1234,
      total_bookmarks: 56,
      is_bookmarked: false,
    },
  }
}

function user(id: number): SessionItem {
  return {
    kind: 'user',
    preview: {
      user: { id, name: `user-${id}`, profile_image: `/avatar-${id}.jpg` },
      illusts: [
        {
          id: id + 100,
          image_urls: { square_medium: `/preview-${id}.jpg` },
        },
      ],
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  testState.search = ''
  testState.gridProps = undefined
  testState.gridHistory = []
  window.localStorage.clear()
  Object.assign(testState.session.state, {
    items: [],
    pages: [],
    cursor: null,
    hasMore: false,
    total: null,
    meta: undefined,
    identityKey: 'pixiv:a',
    generation: 1,
    status: 'ready',
    error: null,
  })
  testState.session.restoreInstruction = null
  Object.defineProperty(window, 'scrollY', { configurable: true, value: 100 })
  window.scrollTo = vi.fn()
  window.scrollBy = vi.fn()
})

describe('Pixiv Phase 2 final blockers', () => {
  it('waits for a measured layout, then restores the stable item across a mode change', async () => {
    testState.search = 'tab=search&q=miku'
    window.localStorage.setItem('pixiv_view_mode', 'list')
    const item = illust(1)
    Object.assign(testState.session.state, { items: [item], pages: [[item]] })
    testState.session.restoreInstruction = {
      key: 'pixiv:a:restore:list',
      identityKey: 'pixiv:a',
      target: {
        kind: 'view',
        view: {
          anchor: { itemId: 'illust:1', offset: 4, scrollY: 100 },
          layout: { columns: 4, width: 1200, mode: 'grid' },
        },
      },
    }

    render(<PixivPage />)

    expect(testState.gridHistory[0]?.columns).toEqual({ base: 1 })
    expect(testState.gridHistory[0]?.restoreRequest).toBeUndefined()

    act(() =>
      testState.gridProps?.onLayoutChange?.({
        colCount: 1,
        containerWidth: 900,
        scrollMargin: 0,
      }),
    )
    await waitFor(() => expect(testState.gridProps?.restoreRequest).toBeDefined())
  })

  it('restores the same stable item after responsive columns and width change', async () => {
    const item = illust(1)
    Object.assign(testState.session.state, { items: [item], pages: [[item]] })
    const snapshotView = {
      anchor: { itemId: 'illust:1', offset: 4, scrollY: 100 },
      layout: { columns: 4, width: 900, mode: 'grid' },
    }
    testState.session.restoreInstruction = {
      key: 'pixiv:a:restore:1',
      identityKey: 'pixiv:a',
      target: { kind: 'view', view: snapshotView },
    }

    render(<PixivPage />)
    act(() =>
      testState.gridProps?.onLayoutChange?.({
        colCount: 3,
        containerWidth: 700,
        scrollMargin: 0,
      }),
    )

    await waitFor(() =>
      expect(testState.gridProps?.restoreRequest).toMatchObject({ index: 0 }),
    )
  })

  it('does not flatten a multi-page buffer for bookmark/follow mutations and refreshes at loaded depth', async () => {
    const first = illust(1)
    const second = illust(2)
    Object.assign(testState.session.state, {
      items: [first, second],
      pages: [[first], [second]],
      cursor: { kind: 'offset', value: 60 },
      hasMore: true,
    })

    const view = render(<PixivPage />)
    fireEvent.click(screen.getAllByRole('button', { name: '☆' })[0])

    expect(testState.replacePage).not.toHaveBeenCalled()
    expect(testState.refresh).toHaveBeenCalledTimes(1)

    Object.assign(testState.session.state, { items: [user(9)], pages: [[user(9)]] })
    view.rerender(<PixivPage />)
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.unfollow' }))
    await waitFor(() => expect(testState.refresh).toHaveBeenCalledTimes(2))
    expect(testState.replacePage).not.toHaveBeenCalled()

    expect(sessionSource).toMatch(
      /kind:\s*'refresh'[\s\S]{0,120}targetDepth:\s*Math\.max\(1,\s*current\.pages\.length\)/,
    )
  })

  it('does not create a second restore request merely because append/refresh changes generation', async () => {
    const item = illust(1)
    Object.assign(testState.session.state, { items: [item], pages: [[item]] })
    testState.session.restoreInstruction = {
      key: 'pixiv:a:restore:generation',
      identityKey: 'pixiv:a',
      target: {
        kind: 'view',
        view: { anchor: { itemId: 'illust:1', offset: 4, scrollY: 100 }, layout: null },
      },
    }
    const view = render(<PixivPage />)
    act(() =>
      testState.gridProps?.onLayoutChange?.({
        colCount: 4,
        containerWidth: 900,
        scrollMargin: 0,
      }),
    )
    await waitFor(() => expect(testState.gridProps?.restoreRequest).toBeDefined())
    const firstRequest = testState.gridProps?.restoreRequest
    expect(firstRequest).toBeDefined()

    act(() => testState.gridProps?.onRestoreApplied?.(firstRequest!))
    expect(testState.acknowledgeRestore).toHaveBeenCalledWith('pixiv:a:restore:generation')
    testState.session.restoreInstruction = null
    view.rerender(<PixivPage />)
    expect(testState.gridProps?.restoreRequest).toBeUndefined()

    testState.session.state.generation += 1
    view.rerender(<PixivPage />)
    expect(testState.gridProps?.restoreRequest).toBeUndefined()
  })

  // A surface change pushes so the previous surface stays reachable by back; a
  // filter change inside the surface replaces. Either way there is exactly one
  // outbound transition, and the view checkpoint must precede it.
  it.each([
    [
      'tab',
      () => fireEvent.click(screen.getByRole('button', { name: 'pixiv.feedTab' })),
      'push' as const,
    ],
    [
      'filter',
      () => fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'weekly' } }),
      'replace' as const,
    ],
  ])(
    'checkpoints before exactly one outbound %s identity transition',
    (_kind, transition, expectedMethod) => {
      render(<PixivPage />)
      transition()

      const used = expectedMethod === 'push' ? testState.push : testState.replace
      const unused = expectedMethod === 'push' ? testState.replace : testState.push

      expect(testState.checkpoint).toHaveBeenCalledTimes(1)
      expect(used).toHaveBeenCalledTimes(1)
      expect(unused).not.toHaveBeenCalled()
      expect(testState.checkpoint.mock.invocationCallOrder[0]).toBeLessThan(
        used.mock.invocationCallOrder[0],
      )
    },
  )

  it('does not checkpoint again when delayed navigation unmounts after the transition task', async () => {
    const view = render(<PixivPage />)
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.feedTab' }))
    expect(testState.checkpoint).toHaveBeenCalledTimes(1)

    await act(async () => Promise.resolve())
    view.unmount()

    expect(testState.checkpoint).toHaveBeenCalledTimes(1)
  })

  it('does not let an outgoing passive cleanup checkpoint into an incoming identity', async () => {
    const outgoing = illust(314)
    Object.assign(testState.session.state, {
      identityKey: 'pixiv:outgoing',
      items: [outgoing],
      pages: [[outgoing]],
    })
    const view = render(<PixivPage />)

    fireEvent.scroll(window)
    await waitFor(() => expect(testState.updateView).toHaveBeenCalled())
    testState.checkpoint.mockClear()

    Object.assign(testState.session.state, {
      identityKey: 'pixiv:incoming',
      items: [],
      pages: [[]],
    })
    view.rerender(<PixivPage />)

    expect(testState.checkpoint).not.toHaveBeenCalled()
  })

  it('rearms an already-restored A after an A to no-anchor B to A round trip', async () => {
    const a = illust(1)
    Object.assign(testState.session.state, { items: [a], pages: [[a]] })
    testState.session.restoreInstruction = {
      key: 'pixiv:a:restore:roundtrip-1',
      identityKey: 'pixiv:a',
      target: {
        kind: 'view',
        view: { anchor: { itemId: 'illust:1', offset: 4, scrollY: 100 }, layout: null },
      },
    }
    const view = render(<PixivPage />)
    act(() =>
      testState.gridProps?.onLayoutChange?.({
        colCount: 4,
        containerWidth: 900,
        scrollMargin: 0,
      }),
    )
    await waitFor(() => expect(testState.gridProps?.restoreRequest).toBeDefined())
    const firstRequest = testState.gridProps?.restoreRequest
    expect(firstRequest).toBeDefined()
    act(() => testState.gridProps?.onRestoreApplied?.(firstRequest!))
    expect(testState.acknowledgeRestore).toHaveBeenCalledWith('pixiv:a:restore:roundtrip-1')
    testState.session.restoreInstruction = null
    view.rerender(<PixivPage />)
    expect(testState.gridProps?.restoreRequest).toBeUndefined()

    Object.assign(testState.session.state, {
      identityKey: 'pixiv:b',
      generation: 2,
      items: [illust(2)],
      pages: [[illust(2)]],
    })
    testState.session.restoreInstruction = {
      key: 'pixiv:b:restore:top',
      identityKey: 'pixiv:b',
      target: { kind: 'top' },
    }
    view.rerender(<PixivPage />)
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0 })
    ;(window.scrollTo as ReturnType<typeof vi.fn>).mockClear()

    Object.assign(testState.session.state, {
      identityKey: 'pixiv:a',
      generation: 3,
      items: [a],
      pages: [[a]],
    })
    testState.session.restoreInstruction = {
      key: 'pixiv:a:restore:roundtrip-2',
      identityKey: 'pixiv:a',
      target: {
        kind: 'view',
        view: { anchor: { itemId: 'illust:1', offset: 4, scrollY: 100 }, layout: null },
      },
    }
    view.rerender(<PixivPage />)
    expect(testState.gridProps?.restoreRequest).toBeDefined()
  })

  it('rejects an A restore callback that arrives after a fast switch to B', async () => {
    const a = illust(1)
    Object.assign(testState.session.state, { items: [a], pages: [[a]] })
    testState.session.restoreInstruction = {
      key: 'pixiv:a:restore:stale',
      identityKey: 'pixiv:a',
      target: {
        kind: 'view',
        view: { anchor: { itemId: 'illust:1', offset: 4, scrollY: 100 }, layout: null },
      },
    }
    const view = render(<PixivPage />)
    act(() =>
      testState.gridProps?.onLayoutChange?.({
        colCount: 4,
        containerWidth: 900,
        scrollMargin: 0,
      }),
    )
    await waitFor(() => expect(testState.gridProps?.restoreRequest).toBeDefined())
    const staleRequest = testState.gridProps?.restoreRequest
    const staleCallback = testState.gridProps?.onRestoreApplied
    expect(staleRequest).toBeDefined()

    const b = illust(2)
    Object.assign(testState.session.state, {
      identityKey: 'pixiv:b',
      generation: 2,
      items: [b],
      pages: [[b]],
    })
    testState.session.restoreInstruction = {
      key: 'pixiv:b:restore:top-after-stale',
      identityKey: 'pixiv:b',
      target: { kind: 'top' },
    }
    view.rerender(<PixivPage />)
    ;(window.scrollBy as ReturnType<typeof vi.fn>).mockClear()

    act(() => staleCallback?.(staleRequest!))
    expect(window.scrollBy).not.toHaveBeenCalled()
  })

  it('routes the visible error Retry through session.retry instead of loadMore', () => {
    Object.assign(testState.session.state, {
      status: 'error',
      error: new Error('failed refresh'),
    })
    render(<PixivPage />)
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }))

    expect(testState.retry).toHaveBeenCalledTimes(1)
    expect(testState.loadMore).not.toHaveBeenCalled()
  })

  it('keeps Pixiv card actions out of the card navigation button DOM', () => {
    const items = [illust(1), user(2)]
    Object.assign(testState.session.state, { items, pages: [items] })
    const { container } = render(<PixivPage />)

    expect(container.querySelector('button button')).toBeNull()
  })

  it('retains illustration tags, view totals, and bookmark totals in list cards', () => {
    testState.search = 'tab=search&q=miku'
    window.localStorage.setItem('pixiv_view_mode', 'list')
    const item = illust(1)
    Object.assign(testState.session.state, { items: [item], pages: [[item]] })

    render(<PixivPage />)

    expect(screen.getByText('tag-one')).toBeInTheDocument()
    expect(screen.getByText(/1,234\s+pixiv\.views/)).toBeInTheDocument()
    expect(screen.getByText(/56\s+pixiv\.bookmarks/)).toBeInTheDocument()
  })

  it('retains an image-error fallback for illustration cards', () => {
    testState.search = 'tab=search&q=miku'
    const item = illust(1)
    Object.assign(testState.session.state, { items: [item], pages: [[item]] })
    render(<PixivPage />)

    const image = screen.getByAltText('illust-1')
    fireEvent.error(image)
    expect(image).toHaveStyle({ display: 'none' })
    expect(pageSource).toMatch(/function IllustCard[\s\S]*?onError=/)
  })

  it('retains the following-user avatar', () => {
    const item = user(2)
    Object.assign(testState.session.state, { items: [item], pages: [[item]] })
    render(<PixivPage />)

    expect(screen.getByAltText('user-2')).toHaveAttribute('src', '/avatar-2.jpg')
  })

  it('retains the following-user no-works fallback', () => {
    const item = user(2)
    if (item.kind !== 'user') throw new Error('Expected a Pixiv user fixture')
    ;(item.preview.illusts as unknown[]) = []
    Object.assign(testState.session.state, { items: [item], pages: [[item]] })
    render(<PixivPage />)

    expect(screen.getByText('pixiv.noWorks')).toBeInTheDocument()
  })

  it('exposes the active Pixiv tab visually or semantically', () => {
    render(<PixivPage />)
    const ranking = screen.getByRole('button', { name: 'browse.ranking' })
    const selected =
      ranking.getAttribute('aria-current') === 'page' ||
      ranking.getAttribute('aria-pressed') === 'true' ||
      ranking.getAttribute('data-state') === 'active' ||
      ranking.className.includes('border-vault-accent')
    expect(selected).toBe(true)
  })

  it('exposes the active grid/list view visually or semantically', () => {
    render(<PixivPage />)
    const grid = screen.getAllByRole('button')[1]
    const selected =
      grid.getAttribute('aria-pressed') === 'true' ||
      grid.getAttribute('data-state') === 'active' ||
      grid.className.includes('bg-vault-input')
    expect(selected).toBe(true)
  })

  it('exposes the active R18 state visually or semantically', () => {
    render(<PixivPage />)
    const r18 = screen.getByRole('button', { name: 'browse.r18' })
    fireEvent.click(r18)
    const selected =
      r18.getAttribute('aria-pressed') === 'true' ||
      r18.getAttribute('data-state') === 'active' ||
      r18.className.includes('bg-pink-600')
    expect(selected).toBe(true)
  })

  it('gives the grid/list icon buttons accessible names', () => {
    render(<PixivPage />)

    expect(screen.getByRole('button', { name: 'browse.gridView' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'browse.listView' })).toBeInTheDocument()
  })
})
