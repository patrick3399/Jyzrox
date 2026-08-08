import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { push, replace, pixivApi, infinite } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  infinite: vi.fn(),
  pixivApi: {
    search: vi.fn(async () => ({ illusts: [], next_offset: null })),
    searchPublic: vi.fn(async () => ({ illusts: [], next_offset: null })),
    ranking: vi.fn(async () => ({ contents: [], rank_total: 0 })),
    getFollowingFeed: vi.fn(async () => ({ illusts: [], next_offset: null })),
    getFollowing: vi.fn(async () => ({ user_previews: [], next_offset: null })),
    getMyBookmarks: vi.fn(async () => ({ illusts: [], next_offset: null })),
    imageProxyUrl: vi.fn((url: string) => url),
  },
}))

let searchStr = ''
let profile: { data?: { username: string }; isLoading: boolean } = { isLoading: false }
let credentials: { data?: { pixiv: { configured: boolean } }; isLoading: boolean } = {
  data: { pixiv: { configured: true } },
  isLoading: false,
}

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))

vi.mock('swr', () => ({ default: () => credentials }))
vi.mock('swr/infinite', () => ({
  default: (
    getKey: (index: number, previous: null) => unknown,
    fetcher: (key: never, options: { signal: AbortSignal }) => unknown,
  ) => {
    infinite(getKey, fetcher)
    const key = getKey(0, null)
    if (key) void fetcher(key as never, { signal: new AbortController().signal })
    return { data: undefined, size: 1, setSize: vi.fn(), isValidating: false, error: null }
  },
}))
vi.mock('@/hooks/useProfile', () => ({ useProfile: () => profile }))
vi.mock('@/lib/api', () => ({
  api: {
    pixiv: pixivApi,
    settings: { getCredentials: vi.fn() },
  },
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/hooks/useScrollRestore', () => ({
  useScrollRestore: () => ({ saveScroll: vi.fn(), restoredPages: null }),
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
vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => <div data-testid="grid" /> }))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import PixivPage from '@/app/pixiv/page'

beforeEach(() => {
  searchStr = ''
  profile = { data: { username: 'alice' }, isLoading: false }
  credentials = { data: { pixiv: { configured: true } }, isLoading: false }
  vi.clearAllMocks()
})

describe('Pixiv URL identity owner', () => {
  it('does not rewrite an incoming tag-search URL to ranking', () => {
    searchStr = 'tab=search&q=blue+archive'
    render(<PixivPage />)

    expect(screen.getByPlaceholderText('pixiv.searchPlaceholder')).toHaveValue('blue archive')
    expect(replace).not.toHaveBeenCalledWith('/pixiv?tab=ranking', expect.anything())
  })

  it('synchronizes mounted state when back/forward supplies a new URL identity', () => {
    const view = render(<PixivPage />)
    replace.mockClear()

    searchStr = 'tab=search&q=back+target&sort=date_asc'
    view.rerender(<PixivPage />)

    expect(screen.getByPlaceholderText('pixiv.searchPlaceholder')).toHaveValue('back target')
    expect(replace).not.toHaveBeenCalledWith('/pixiv?tab=ranking', expect.anything())
  })

  it('emits exactly one outbound URL transition for a submitted search', () => {
    render(<PixivPage />)
    replace.mockClear()
    const input = screen.getByPlaceholderText('pixiv.searchPlaceholder')

    fireEvent.change(input, { target: { value: 'miku' } })
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.search' }))

    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenCalledWith('/pixiv?tab=search&q=miku', { scroll: false })
  })

  it('emits exactly one canonical URL transition for each search filter change', () => {
    searchStr = 'tab=search&q=miku'
    render(<PixivPage />)
    const [sort, duration] = screen.getAllByRole('combobox')

    replace.mockClear()
    fireEvent.change(sort, { target: { value: 'popular_desc' } })
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenLastCalledWith('/pixiv?tab=search&q=miku&sort=popular_desc', {
      scroll: false,
    })

    replace.mockClear()
    fireEvent.change(duration, { target: { value: 'within_last_week' } })
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenLastCalledWith(
      '/pixiv?tab=search&q=miku&sort=popular_desc&duration=within_last_week',
      { scroll: false },
    )
  })

  it('emits exactly one canonical URL transition for ranking filters and R18', () => {
    render(<PixivPage />)
    const [mode, content] = screen.getAllByRole('combobox')

    replace.mockClear()
    fireEvent.change(mode, { target: { value: 'weekly' } })
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenLastCalledWith('/pixiv?tab=ranking&mode=weekly', {
      scroll: false,
    })

    replace.mockClear()
    fireEvent.change(content, { target: { value: 'manga' } })
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenLastCalledWith('/pixiv?tab=ranking&mode=weekly&content=manga', {
      scroll: false,
    })

    replace.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'browse.r18' }))
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenLastCalledWith('/pixiv?tab=ranking&mode=weekly&r18=1', {
      scroll: false,
    })
  })

  it('emits exactly one canonical URL transition for bookmark visibility', () => {
    render(<PixivPage />)
    fireEvent.click(screen.getByRole('button', { name: 'pixiv.bookmarks' }))

    replace.mockClear()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'private' } })

    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenLastCalledWith('/pixiv?tab=bookmarks&restrict=private', {
      scroll: false,
    })
  })
})

describe('Pixiv scoped fetch readiness', () => {
  it('does not fetch any surface while profile and credentials are unresolved', () => {
    profile = { isLoading: true }
    credentials = { isLoading: true }

    render(<PixivPage />)

    expect(pixivApi.ranking).not.toHaveBeenCalled()
    expect(pixivApi.search).not.toHaveBeenCalled()
    expect(pixivApi.searchPublic).not.toHaveBeenCalled()
    expect(pixivApi.getFollowingFeed).not.toHaveBeenCalled()
    expect(pixivApi.getFollowing).not.toHaveBeenCalled()
    expect(pixivApi.getMyBookmarks).not.toHaveBeenCalled()
  })
})
