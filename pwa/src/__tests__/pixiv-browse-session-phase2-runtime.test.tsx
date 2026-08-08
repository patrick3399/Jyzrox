import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PixivBrowseItem } from '@/lib/browse/pixiv'

type GridProps = {
  items: PixivBrowseItem[]
  renderItem: (item: PixivBrowseItem, index: number) => React.ReactNode
  restoreRequest?: { key: string; index: number }
  onLayoutChange?: (layout: {
    colCount: number
    containerWidth: number
    scrollMargin: number
  }) => void
}

const runtime = vi.hoisted(() => ({
  events: [] as string[],
  push: vi.fn(),
  replace: vi.fn(),
  checkpoint: vi.fn(),
  loadMore: vi.fn(),
  refresh: vi.fn(),
  retry: vi.fn(),
  replacePage: vi.fn(),
  gridProps: null as GridProps | null,
  state: {
    identityKey: 'ranking:daily',
    items: [] as PixivBrowseItem[],
    pages: [] as PixivBrowseItem[][],
    cursor: null,
    hasMore: false,
    total: null,
    generation: 1,
    status: 'idle' as 'idle' | 'loading' | 'error',
    error: null as Error | null,
    requestKind: null,
    failedRequest: null,
    terminal: null,
    meta: null,
  },
  restoreInstruction: null as null | {
    key: string
    identityKey: string
    target:
      | { kind: 'top' }
      | {
          kind: 'view'
          view: {
            anchor: { itemId: string; offset: number; scrollY: number } | null
            layout: { columns: number; width: number; mode: string } | null
          }
        }
  },
  acknowledgeRestore: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (url: string) => {
      runtime.events.push(`push:${url}`)
      runtime.push(url)
    },
    replace: (url: string, options: unknown) => {
      runtime.events.push(`replace:${url}`)
      runtime.replace(url, options)
    },
  }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('swr', () => ({
  default: () => ({ data: { pixiv: { configured: true } }, isLoading: false }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'alice' }, isLoading: false }),
}))
vi.mock('@/hooks/usePixivBrowseSession', () => ({
  usePixivBrowseSession: () => ({
    state: runtime.state,
    checkpoint: (view: unknown) => {
      runtime.events.push('checkpoint')
      return runtime.checkpoint(view)
    },
    loadMore: runtime.loadMore,
    refresh: runtime.refresh,
    retry: runtime.retry,
    replacePage: runtime.replacePage,
    restoreInstruction: runtime.restoreInstruction,
    acknowledgeRestore: runtime.acknowledgeRestore,
    updateView: vi.fn(),
  }),
}))
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/hooks/useIllustActions', () => ({
  useIllustActions: (
    _illust: unknown,
    onBookmarkChanged?: (bookmarked: boolean) => void | Promise<void>,
  ) => ({
    downloading: false,
    bookmarked: false,
    bookmarking: false,
    handleDownload: vi.fn(),
    handleBookmark: async (event: { preventDefault: () => void; stopPropagation: () => void }) => {
      event.preventDefault()
      event.stopPropagation()
      await onBookmarkChanged?.(true)
    },
  }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: GridProps) => {
    runtime.gridProps = props
    return (
      <div data-testid="grid">
        {props.items.map((item, index) => (
          <div key={`${item.kind}:${index}`}>{props.renderItem(item, index)}</div>
        ))}
      </div>
    )
  },
}))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getCredentials: vi.fn() },
    pixiv: {
      imageProxyUrl: (url: string) => url,
      followUser: vi.fn(),
      unfollowUser: vi.fn(),
    },
  },
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import PixivPage from '@/app/pixiv/page'

function illustItem(id = 11): PixivBrowseItem {
  return {
    kind: 'illust',
    illust: {
      id,
      title: `Illust ${id}`,
      image_urls: { square_medium: '/thumb.jpg' },
      user: { name: 'Artist' },
      page_count: 1,
      is_bookmarked: false,
    },
  }
}

beforeEach(() => {
  runtime.events.length = 0
  runtime.push.mockClear()
  runtime.replace.mockClear()
  runtime.checkpoint.mockClear()
  runtime.loadMore.mockClear()
  runtime.refresh.mockClear()
  runtime.retry.mockClear()
  runtime.replacePage.mockClear()
  runtime.gridProps = null
  runtime.state.identityKey = 'ranking:daily'
  runtime.state.items = []
  runtime.state.pages = []
  runtime.state.hasMore = false
  runtime.state.generation = 1
  runtime.state.status = 'idle'
  runtime.state.error = null
  runtime.restoreInstruction = null
  runtime.acknowledgeRestore.mockClear()
})

describe('Pixiv Phase 2 runtime ownership', () => {
  it('checkpoints the outgoing view before a canonical filter transition', () => {
    render(<PixivPage />)
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'weekly' } })

    expect(runtime.events.slice(-2)).toEqual([
      'checkpoint',
      'replace:/pixiv?tab=ranking&mode=weekly',
    ])
  })

  it('retries the failed session request instead of starting a fresh append', () => {
    runtime.state.status = 'error'
    runtime.state.error = new Error('network')
    render(<PixivPage />)

    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }))

    expect(runtime.retry).toHaveBeenCalledOnce()
    expect(runtime.loadMore).not.toHaveBeenCalled()
  })

  it('refreshes after a bookmark mutation without replacing the loaded page boundaries', () => {
    runtime.state.identityKey = 'feed'
    runtime.state.items = [illustItem()]
    runtime.state.pages = [[illustItem()]]
    render(<PixivPage />)

    fireEvent.click(screen.getByRole('button', { name: '☆' }))

    expect(runtime.refresh).toHaveBeenCalledOnce()
    expect(runtime.replacePage).not.toHaveBeenCalled()
  })

  it('keeps the measured restore token stable when request generation advances', () => {
    runtime.state.items = [illustItem()]
    runtime.restoreInstruction = {
      key: 'ranking:daily:restore:1',
      identityKey: 'ranking:daily',
      target: {
        kind: 'view',
        view: { anchor: { itemId: 'illust:11', offset: 8, scrollY: 300 }, layout: null },
      },
    }
    const view = render(<PixivPage />)
    act(() =>
      runtime.gridProps?.onLayoutChange?.({
        colCount: 4,
        containerWidth: 900,
        scrollMargin: 0,
      }),
    )
    const firstKey = runtime.gridProps?.restoreRequest?.key

    runtime.state.generation = 2
    view.rerender(<PixivPage />)

    expect(firstKey).toBe('ranking:daily:restore:1')
    expect(runtime.gridProps?.restoreRequest?.key).toBe(firstKey)
  })

  it('checkpoints before opening a Following user', () => {
    runtime.state.identityKey = 'following:public'
    runtime.state.items = [
      {
        kind: 'user',
        preview: { user: { id: 23, name: 'Artist 23' }, illusts: [] },
      },
    ]
    render(<PixivPage />)

    fireEvent.click(screen.getByRole('button', { name: /Artist 23/ }))

    expect(runtime.events.slice(-2)).toEqual(['checkpoint', 'push:/pixiv/user/23'])
  })
})
