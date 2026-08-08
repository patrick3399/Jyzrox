import { act, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const sessionModel = vi.hoisted(() => ({
  identityKey: 'library:A',
  restoreInstruction: null as null | {
    key: string
    identityKey: string
    target:
      | { kind: 'top' }
      | {
          kind: 'view'
          view: {
            anchor: { itemId: number | null; offset: number; scrollY: number } | null
            layout: null
          }
        }
  },
}))
const checkpoint = vi.hoisted(() => vi.fn())
const updateView = vi.hoisted(() => vi.fn())
const acknowledgeRestore = vi.hoisted(() => vi.fn())
const gridModel = vi.hoisted(() => ({ props: null as Record<string, unknown> | null }))

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/hooks/useUnifiedSearch', () => ({
  useUnifiedSearch: () => ({
    rawQuery: '',
    inputValue: '',
    parsed: {
      tags: [],
      nameOnlyTags: [],
      excludeTags: [],
      title: null,
      source: null,
      rating: null,
      favorited: false,
      readingList: false,
      collection: null,
      artistId: null,
      category: null,
      importMode: null,
      sort: null,
    },
    setFilter: vi.fn(),
    commitSearch: vi.fn(),
    handleInputChange: vi.fn(),
    selectMode: false,
    setSelectMode: vi.fn(),
    selectedIds: new Set<number>(),
    setSelectedIds: vi.fn(),
  }),
}))
vi.mock('@/hooks/useLibraryBrowseSession', () => ({
  useLibraryBrowseSession: () => ({
    state: {
      identityKey: sessionModel.identityKey,
      items: [
        {
          id: 1,
          title: 'Gallery',
          title_jpn: null,
          source: 'local',
          source_id: 'gallery-1',
          category: null,
          language: null,
          pages: 1,
          rating: 0,
          favorited: false,
          is_favorited: false,
          my_rating: null,
          in_reading_list: false,
          artist_id: null,
          import_mode: null,
          source_url: null,
          tags_array: [],
          uploader: null,
          download_status: 'completed',
          added_at: null,
          posted_at: null,
          tags: [],
        },
      ],
      total: 1,
      status: 'idle',
      error: null,
      hasMore: false,
    },
    loadMore: vi.fn(),
    refresh: vi.fn(),
    retry: vi.fn(),
    checkpoint,
    updateView,
    restoreInstruction: sessionModel.restoreInstruction,
    acknowledgeRestore,
  }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'member', role: 'member' } }),
}))
vi.mock('@/hooks/useGalleries', () => ({
  useGalleryCategories: () => ({ data: { categories: [] } }),
  useLibrarySources: () => ({ data: [] }),
}))
vi.mock('@/hooks/useCollections', () => ({
  useCollections: () => ({ data: { collections: [] } }),
}))
vi.mock('@/hooks/useDatasets', () => ({
  useDatasets: () => ({ data: { datasets: [] } }),
  useAddDatasetMembers: () => ({ trigger: vi.fn() }),
}))
vi.mock('@/hooks/useDisplayPreferences', () => ({
  useDisplayPreferences: () => ({ gallery_grid_density: 'comfortable', gallery_grid_columns: 4 }),
}))
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: {
    items: unknown[]
    renderItem: (item: never) => React.ReactNode
    restoreRequest?: { key: string; index: number }
  }) => {
    gridModel.props = props as unknown as Record<string, unknown>
    return (
      <div>
        {props.items.map((item, index) => (
          <div key={index}>{props.renderItem(item as never)}</div>
        ))}
      </div>
    )
  },
}))
vi.mock('@/components/GalleryCard', () => ({
  LibraryGalleryCard: ({ gallery }: { gallery: { title: string } }) => <div>{gallery.title}</div>,
}))
vi.mock('@/components/GalleryListCard', () => ({
  GalleryListCard: ({ gallery }: { gallery: { title: string } }) => <div>{gallery.title}</div>,
}))
vi.mock('@/lib/api', () => ({ api: { library: {} } }))

import LibraryPage from '@/app/library/page'

describe('Library restore and persistence lifecycle', () => {
  let frames: Map<number, FrameRequestCallback>
  let nextFrame: number

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    sessionModel.identityKey = 'library:A'
    sessionModel.restoreInstruction = null
    gridModel.props = null
    frames = new Map()
    nextFrame = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = ++nextFrame
      frames.set(id, callback)
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
    vi.stubGlobal('scrollTo', vi.fn())
    Object.defineProperty(window, 'scrollY', { value: 900, configurable: true })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('checkpoints after scroll settle and again on pagehide', () => {
    render(<LibraryPage />)

    fireEvent.scroll(window)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
      vi.advanceTimersByTime(250)
    })
    expect(updateView).toHaveBeenCalled()
    expect(checkpoint).toHaveBeenCalledOnce()

    fireEvent(window, new Event('pagehide'))
    expect(checkpoint).toHaveBeenCalledTimes(2)
  })

  it('re-applies A after an already-restored A to no-anchor B to A round trip', () => {
    sessionModel.restoreInstruction = {
      key: 'library:A:restore:1',
      identityKey: 'library:A',
      target: {
        kind: 'view',
        view: { anchor: { itemId: null, offset: 0, scrollY: 500 }, layout: null },
      },
    }
    const view = render(<LibraryPage />)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
    })
    expect(window.scrollTo).toHaveBeenCalledWith(0, 500)

    sessionModel.identityKey = 'library:B'
    sessionModel.restoreInstruction = {
      key: 'library:B:restore:1',
      identityKey: 'library:B',
      target: { kind: 'top' },
    }
    view.rerender(<LibraryPage />)
    sessionModel.identityKey = 'library:A'
    sessionModel.restoreInstruction = {
      key: 'library:A:restore:2',
      identityKey: 'library:A',
      target: {
        kind: 'view',
        view: { anchor: { itemId: null, offset: 0, scrollY: 700 }, layout: null },
      },
    }
    view.rerender(<LibraryPage />)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
    })

    expect(window.scrollTo).toHaveBeenCalledTimes(2)
    expect(window.scrollTo).toHaveBeenLastCalledWith(0, 700)
    expect(acknowledgeRestore).toHaveBeenLastCalledWith('library:A:restore:2')
  })

  it('cancels A pixel restoration when identity B commits before its animation frame', () => {
    sessionModel.restoreInstruction = {
      key: 'library:A:restore:stale',
      identityKey: 'library:A',
      target: {
        kind: 'view',
        view: { anchor: { itemId: null, offset: 0, scrollY: 500 }, layout: null },
      },
    }
    const view = render(<LibraryPage />)

    sessionModel.identityKey = 'library:B'
    sessionModel.restoreInstruction = {
      key: 'library:B:restore:top',
      identityKey: 'library:B',
      target: { kind: 'top' },
    }
    view.rerender(<LibraryPage />)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
    })

    expect(window.scrollTo).toHaveBeenCalledOnce()
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0)
    expect(acknowledgeRestore).toHaveBeenCalledWith('library:B:restore:top')
  })

  it('applies a missing-identity top instruction exactly once and acknowledges it', () => {
    sessionModel.identityKey = 'library:missing'
    sessionModel.restoreInstruction = {
      key: 'library:missing:1',
      identityKey: 'library:missing',
      target: { kind: 'top' },
    }
    const view = render(<LibraryPage />)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
    })

    expect(window.scrollTo).toHaveBeenCalledTimes(1)
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0)
    expect(acknowledgeRestore).toHaveBeenCalledOnce()
    expect(acknowledgeRestore).toHaveBeenCalledWith('library:missing:1')

    view.rerender(<LibraryPage />)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
    })
    expect(window.scrollTo).toHaveBeenCalledTimes(1)
  })

  it('clears a pending grid request when the same restore key falls back to pixels', () => {
    sessionModel.restoreInstruction = {
      key: 'library:A:restore:refresh',
      identityKey: 'library:A',
      target: {
        kind: 'view',
        view: { anchor: { itemId: 1, offset: 8, scrollY: 600 }, layout: null },
      },
    }
    const view = render(<LibraryPage />)
    expect(gridModel.props?.restoreRequest).toEqual({
      key: 'library:A:restore:refresh',
      identityKey: 'library:A',
      index: 0,
    })

    sessionModel.restoreInstruction = {
      key: 'library:A:restore:refresh',
      identityKey: 'library:A',
      target: {
        kind: 'view',
        view: { anchor: { itemId: 999, offset: 8, scrollY: 600 }, layout: null },
      },
    }
    view.rerender(<LibraryPage />)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
    })

    expect(gridModel.props?.restoreRequest).toBeUndefined()
    updateView.mockClear()
    fireEvent.scroll(window)
    act(() => {
      for (const [id, callback] of frames) {
        frames.delete(id)
        callback(0)
      }
    })
    expect(updateView).toHaveBeenCalledOnce()
  })
})
