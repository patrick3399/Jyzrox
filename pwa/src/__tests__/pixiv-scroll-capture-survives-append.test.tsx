/**
 * The scroll listener captures into a requestAnimationFrame, but the effect that
 * owns the listener also depended on `captureView`/`persistView`, which are
 * rebuilt whenever `state.items` changes. An append that committed before the
 * frame fired tore the effect down, cancelled the frame, and dropped that scroll
 * position without rescheduling it — and infinite scroll makes that window
 * routine, because scrolling is what triggers the append.
 */
import { act, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PixivBrowseItem } from '@/lib/browse/pixiv'

type GridProps = {
  items: PixivBrowseItem[]
  renderItem: (item: PixivBrowseItem, index: number) => React.ReactNode
}

const illust = (id: number) =>
  ({
    kind: 'illust',
    illust: {
      id,
      title: `Illust ${id}`,
      image_urls: { square_medium: `https://example.test/${id}.jpg` },
      user: { id: 1, name: 'Artist' },
      page_count: 1,
      tags: [],
      total_view: 0,
      total_bookmarks: 0,
    },
  }) as unknown as PixivBrowseItem

const runtime = vi.hoisted(() => ({
  itemCount: 1,
  updateView: vi.fn(),
  checkpoint: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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
    state: {
      identityKey: 'ranking:daily',
      items: Array.from({ length: runtime.itemCount }, (_, index) => illust(index + 1)),
      pages: [],
      cursor: null,
      hasMore: true,
      total: null,
      generation: 1,
      status: 'idle',
      error: null,
      requestKind: null,
      failedRequest: null,
      terminal: null,
      meta: null,
    },
    checkpoint: runtime.checkpoint,
    updateView: runtime.updateView,
    loadMore: vi.fn(),
    refresh: vi.fn(),
    retry: vi.fn(),
    replacePage: vi.fn(),
    restoreInstruction: null,
    acknowledgeRestore: vi.fn(),
  }),
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
  VirtualGrid: (props: GridProps) => (
    <div>{props.items.map((item, index) => props.renderItem(item, index))}</div>
  ),
}))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: vi.fn() }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getCredentials: vi.fn() },
    pixiv: { imageProxyUrl: (url: string) => url, followUser: vi.fn(), unfollowUser: vi.fn() },
  },
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import PixivPage from '@/app/pixiv/page'

describe('root Pixiv scroll capture vs a concurrent append', () => {
  let frames: Map<number, FrameRequestCallback>
  let nextFrame: number

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    runtime.itemCount = 1
    frames = new Map()
    nextFrame = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = ++nextFrame
      frames.set(id, callback)
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
    vi.stubGlobal('scrollTo', vi.fn())
    Object.defineProperty(window, 'scrollY', { value: 900, configurable: true, writable: true })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const runFrames = () => {
    act(() => {
      for (const callback of [...frames.values()]) callback(0)
      frames.clear()
    })
  }

  it('a scroll captured before an append commits is still recorded after it commits', () => {
    const view = render(<PixivPage />)
    runtime.updateView.mockClear()

    fireEvent.scroll(window)
    expect(frames.size).toBe(1)

    // The append commits while that capture frame is still pending.
    runtime.itemCount = 2
    act(() => {
      view.rerender(<PixivPage />)
    })
    runFrames()

    expect(runtime.updateView).toHaveBeenCalled()
    expect(runtime.updateView.mock.calls.at(-1)?.[0]).toMatchObject({ anchor: { scrollY: 900 } })
  })
})
