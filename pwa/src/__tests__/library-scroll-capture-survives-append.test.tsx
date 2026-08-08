import { act, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const sessionModel = vi.hoisted(() => ({
  identityKey: 'library:A',
  extraItem: false,
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
function gallery(id: number) {
  return {
    id,
    title: `Gallery ${id}`,
    title_jpn: null,
    source: 'local',
    source_id: `gallery-${id}`,
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
  }
}

vi.mock('@/hooks/useLibraryBrowseSession', () => ({
  useLibraryBrowseSession: () => ({
    state: {
      identityKey: sessionModel.identityKey,
      items: sessionModel.extraItem ? [gallery(1), gallery(2)] : [gallery(1)],
      total: sessionModel.extraItem ? 2 : 1,
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


/**
 * The scroll listener captures into a requestAnimationFrame, but the effect that
 * owns the listener also depended on `captureAnchor`, which is rebuilt whenever
 * the gallery list changes. An append that committed before the frame fired tore
 * the effect down, cancelled the frame, and dropped that scroll position without
 * rescheduling it — and infinite scroll makes that window routine, because
 * scrolling is what triggers the append.
 */
describe('Library scroll capture vs a concurrent append', () => {
  let frames: Map<number, FrameRequestCallback>
  let nextFrame: number

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    sessionModel.identityKey = 'library:A'
    sessionModel.restoreInstruction = null
    sessionModel.extraItem = false
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

  const runFrames = () => {
    act(() => {
      for (const callback of [...frames.values()]) callback(0)
      frames.clear()
    })
  }

  it('a scroll captured before an append commits is still recorded after it commits', () => {
    const view = render(<LibraryPage />)

    fireEvent.scroll(window)
    expect(frames.size).toBe(1)

    // The append commits while that capture frame is still pending.
    sessionModel.extraItem = true
    act(() => {
      view.rerender(<LibraryPage />)
    })
    runFrames()

    expect(updateView).toHaveBeenCalled()
    expect(updateView.mock.calls.at(-1)?.[0]).toMatchObject({ anchor: { scrollY: 900 } })
  })
})
