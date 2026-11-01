/**
 * Library page: view controls in the search block and anchored layout switching.
 *
 * Switching layout while the sticky search bar is stuck keeps the first visible
 * card in place: the page snapshots it, writes the preference and the view at
 * click time, then asks the grid to land on that card once the new layout is
 * rendered. The grid itself is mocked; these tests drive its callbacks.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GRID_COLUMNS_KEY, GRID_DENSITY_KEY, GRID_DENSITY_OVERRIDE_KEY } from '@/lib/uiPreferences'
import { getLibraryGridColumns } from '@/lib/libraryLayout'

type RestoreRequest = { key: string; index: number }
type GridProps = {
  items: Array<{ id: number }>
  columns: Record<string, number>
  gap: number
  renderItem: (item: never) => React.ReactNode
  onRegisterElement?: (index: number, element: HTMLElement | null) => void
  onVisibleRangeChange?: (range: {
    startIndex: number
    endIndex: number
    visibleStartIndex?: number
  }) => void
  restoreRequest?: RestoreRequest
  onRestoreApplied?: (request: RestoreRequest) => void
}

const model = vi.hoisted(() => ({
  identityKey: 'library:A',
  items: [] as unknown[],
  restoreInstruction: null as null | Record<string, unknown>,
  tops: new Map<number, number>(),
}))
const checkpoint = vi.hoisted(() => vi.fn())
const updateView = vi.hoisted(() => vi.fn())
const acknowledgeRestore = vi.hoisted(() => vi.fn())
const gridModel = vi.hoisted(() => ({ props: null as unknown }))

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
    clearFilters: vi.fn(),
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
      identityKey: model.identityKey,
      items: model.items,
      total: model.items.length,
      status: 'idle',
      error: null,
      hasMore: false,
    },
    loadMore: vi.fn(),
    refresh: vi.fn(),
    retry: vi.fn(),
    checkpoint,
    updateView,
    restoreInstruction: model.restoreInstruction,
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
vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: null, registerElement: vi.fn() }),
}))
vi.mock('@/components/VirtualGrid', () => ({
  VirtualGrid: (props: GridProps) => {
    gridModel.props = props
    return (
      <div>
        {props.items.map((item, index) => (
          <div
            key={item.id}
            data-testid={`card-${item.id}`}
            ref={(element) => {
              if (element) {
                element.getBoundingClientRect = () => {
                  const top = model.tops.get(item.id) ?? 0
                  return { top, bottom: top + CARD_HEIGHT, left: 0, right: 100 } as DOMRect
                }
              }
              props.onRegisterElement?.(index, element)
            }}
          >
            {props.renderItem(item as never)}
          </div>
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

const CARD_HEIGHT = 200
const BAR_BOTTOM = 60
const GAP = 8
const SCROLL_Y = 900
const IDS = Array.from({ length: 12 }, (_, i) => i + 1)

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

let frames: Map<number, FrameRequestCallback>
let nextFrame: number
let scrollY: number
let scrollTo: ReturnType<typeof vi.fn>

const grid = () => gridModel.props as GridProps
const flush = () =>
  act(() => {
    for (const callback of [...frames.values()]) callback(0)
    frames.clear()
  })

function setIds(ids: number[]) {
  model.items = ids.map(gallery)
}

/** Card tops such that `first` (an index) is the first card below the bar. */
function setTops(ids: number[], first: number) {
  model.tops = new Map(ids.map((id, index) => [id, BAR_BOTTOM + GAP + (index - first) * 220]))
}

function reportVisibleStart(visibleStartIndex: number, startIndex = 0) {
  act(() => {
    grid().onVisibleRangeChange?.({ startIndex, endIndex: IDS.length - 1, visibleStartIndex })
  })
}

function scrollWindowTo(y: number) {
  scrollY = y
  fireEvent.scroll(window)
  flush()
}

function mount({ stuck = true, first = 6, ids = IDS }: { stuck?: boolean; first?: number; ids?: number[] } = {}) {
  setIds(ids)
  setTops(ids, first)
  const view = render(<LibraryPage />)
  const block = screen.getByTestId('library-search-block')
  block.getBoundingClientRect = () => ({ top: 0, bottom: BAR_BOTTOM }) as DOMRect
  const sentinel = block.previousElementSibling as HTMLElement
  sentinel.getBoundingClientRect = () => ({ top: stuck ? -400 : 120 }) as DOMRect
  scrollWindowTo(scrollY)
  reportVisibleStart(first)
  vi.clearAllMocks()
  scrollTo.mockClear()
  return { view, block }
}

const clickLayout = (name: 'Grid view' | 'List view') =>
  fireEvent.click(
    within(screen.getByTestId('library-view-inline')).getByRole('radio', { name }),
  )

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  model.identityKey = 'library:A'
  model.restoreInstruction = null
  model.tops = new Map()
  gridModel.props = null
  frames = new Map()
  nextFrame = 0
  scrollY = SCROLL_Y
  scrollTo = vi.fn((_x: number, y: number) => {
    scrollY = y
  })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = ++nextFrame
    frames.set(id, callback)
    return id
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
  vi.stubGlobal('scrollTo', scrollTo)
  Object.defineProperty(window, 'scrollY', { get: () => scrollY, configurable: true })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Library view controls placement', () => {
  it('test_view_controls_live_in_the_search_block_and_not_in_the_header', () => {
    mount()

    const block = screen.getByTestId('library-search-block')
    expect(within(block).getByTestId('library-view-menu-button')).toBeInTheDocument()
    expect(within(block).getByTestId('library-view-inline')).toBeInTheDocument()
    expect(within(block).getByTestId('library-density-button')).toBeInTheDocument()
    const header = screen.getByRole('heading', { name: 'Library' }).closest('header') as HTMLElement
    expect(within(header).queryByTestId('library-view-inline')).toBeNull()
    expect(within(header).queryByTestId('library-view-menu-button')).toBeNull()
  })

  it('test_density_control_is_absent_in_list_mode_and_back_in_grid_mode', () => {
    mount({ stuck: false })

    clickLayout('List view')
    expect(screen.queryByTestId('library-density-button')).toBeNull()
    expect(grid().columns).toEqual({ base: 1 })

    clickLayout('Grid view')
    expect(screen.getByTestId('library-density-button')).toBeInTheDocument()
  })

  it('test_choosing_a_density_writes_the_override_and_leaves_settings_untouched', async () => {
    localStorage.setItem(GRID_DENSITY_KEY, 'spacious')
    localStorage.setItem(GRID_COLUMNS_KEY, '6')
    mount({ stuck: false })
    // Fixed Settings columns apply while there is no override.
    expect(grid().columns).toEqual(getLibraryGridColumns('spacious', 6))

    fireEvent.click(screen.getByTestId('library-density-button'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Compact' }))

    expect(localStorage.getItem(GRID_DENSITY_OVERRIDE_KEY)).toBe('compact')
    expect(localStorage.getItem(GRID_DENSITY_KEY)).toBe('spacious')
    expect(localStorage.getItem(GRID_COLUMNS_KEY)).toBe('6')
    // Override: that density's auto columns, the fixed 6 is ignored.
    expect(grid().columns).toEqual(getLibraryGridColumns('compact'))
    expect(grid().gap).toBe(8)

    fireEvent.click(within(dialog).getByText('Follow settings'))

    expect(localStorage.getItem(GRID_DENSITY_OVERRIDE_KEY)).toBeNull()
    expect(grid().columns).toEqual(getLibraryGridColumns('spacious', 6))
    expect(localStorage.getItem(GRID_DENSITY_KEY)).toBe('spacious')
  })

  it('test_layout_choice_is_persisted_as_a_valid_view_mode', () => {
    localStorage.setItem('library_view_mode', 'bogus')
    mount({ stuck: false })
    // A raw cast of 'bogus' would render the grid as neither mode.
    expect(grid().columns).not.toEqual({ base: 1 })
    expect(screen.getByTestId('library-density-button')).toBeInTheDocument()

    clickLayout('List view')

    expect(localStorage.getItem('library_view_mode')).toBe('list')
  })
})

describe('Library layout switch while the search bar is stuck', () => {
  it('test_switch_mid_scroll_targets_the_first_visible_card_not_the_overscan_start', () => {
    const { } = mount({ first: 6 })
    // The grid reports overscan start 0 but the first card on screen is index 6.
    reportVisibleStart(6, 0)

    clickLayout('List view')

    const request = grid().restoreRequest
    expect(request).toEqual({ key: 'layout-switch:1', index: 6 })
    expect(request?.index).not.toBe(0)
    expect(checkpoint.mock.calls[0][0].anchor).toEqual({
      itemId: IDS[6],
      offset: BAR_BOTTOM + GAP,
      scrollY: SCROLL_Y,
    })
  })

  it('test_switch_walks_back_over_cards_still_below_the_bar_when_the_visible_start_is_stale', () => {
    mount({ first: 4 })
    // Reported visible start (6) is stale: cards 4 and 5 are still below the bar.
    reportVisibleStart(6, 0)

    clickLayout('List view')

    expect(grid().restoreRequest?.index).toBe(4)
  })

  it('test_routine_scroll_capture_anchors_on_the_first_visible_row_not_the_overscan_start', () => {
    mount({ first: 6 })
    reportVisibleStart(6, 0)

    scrollWindowTo(SCROLL_Y + 50)

    const anchor = updateView.mock.calls.at(-1)?.[0].anchor
    expect(anchor.itemId).toBe(IDS[6])
    expect(anchor.itemId).not.toBe(IDS[0])
  })

  it('test_switch_during_append_still_lands', () => {
    const { view } = mount({ first: 6 })
    clickLayout('List view')
    const issued = grid().restoreRequest
    expect(issued).toEqual({ key: 'layout-switch:1', index: 6 })

    // The list grows while the switch is pending.
    const appended = [...IDS, 13, 14]
    setIds(appended)
    setTops(appended, 6)
    view.rerender(<LibraryPage />)

    expect(grid().restoreRequest).toEqual(issued)
    model.tops.set(IDS[6], 300)
    act(() => grid().onRestoreApplied?.(grid().restoreRequest as RestoreRequest))

    expect(scrollTo).toHaveBeenCalledWith(0, SCROLL_Y + 300 - (BAR_BOTTOM + GAP))
    expect(grid().restoreRequest).toBeUndefined()
  })

  it('test_switch_with_no_later_scroll_has_already_checkpointed_the_card_and_new_mode', () => {
    mount({ first: 6 })

    clickLayout('List view')

    // No scroll event or frame has run since the click.
    expect(frames.size).toBe(0)
    expect(checkpoint).toHaveBeenCalledTimes(1)
    expect(checkpoint.mock.calls[0][0]).toMatchObject({
      anchor: { itemId: IDS[6], offset: BAR_BOTTOM + GAP },
      layout: { mode: 'list' },
    })
    expect(updateView.mock.calls[0][0]).toMatchObject({
      anchor: { itemId: IDS[6] },
      layout: { mode: 'list' },
    })
    expect(localStorage.getItem('library_view_mode')).toBe('list')

    // Leaving the page right away saves the same card, not a re-captured one.
    model.tops.set(IDS[0], BAR_BOTTOM + GAP)
    checkpoint.mockClear()
    fireEvent(window, new Event('pagehide'))
    expect(checkpoint.mock.calls[0][0]).toMatchObject({
      anchor: { itemId: IDS[6] },
      layout: { mode: 'list' },
    })
  })

  it('test_landing_scrolls_then_saves_the_view_from_the_landing_position', () => {
    mount({ first: 6 })
    clickLayout('List view')
    updateView.mockClear()
    checkpoint.mockClear()
    model.tops.set(IDS[6], 300)

    act(() => grid().onRestoreApplied?.(grid().restoreRequest as RestoreRequest))

    const landingY = SCROLL_Y + 300 - (BAR_BOTTOM + GAP)
    expect(scrollTo).toHaveBeenCalledWith(0, landingY)
    const scrollOrder = scrollTo.mock.invocationCallOrder[0]
    expect(updateView.mock.invocationCallOrder[0]).toBeGreaterThan(scrollOrder)
    expect(checkpoint.mock.invocationCallOrder[0]).toBeGreaterThan(scrollOrder)
    expect(updateView.mock.calls[0][0]).toMatchObject({
      anchor: { itemId: IDS[6], scrollY: landingY },
      layout: { mode: 'list' },
    })
    expect(checkpoint.mock.calls[0][0].anchor.scrollY).toBe(landingY)
  })

  it('test_bar_stays_visible_after_the_landing_jump_scrolls_the_page_down', () => {
    const { block } = mount({ first: 6 })
    clickLayout('List view')
    model.tops.set(IDS[6], 900)
    act(() => grid().onRestoreApplied?.(grid().restoreRequest as RestoreRequest))
    expect(scrollY).toBe(SCROLL_Y + 900 - (BAR_BOTTOM + GAP))

    // The jump's scroll event arrives after the lock has been released.
    scrollWindowTo(scrollY)

    expect(block).not.toHaveAttribute('data-scroll-hidden')
  })

  it('test_bar_stays_revealed_while_a_switch_is_pending_even_when_scrolling_down', () => {
    const { block } = mount({ first: 6 })
    clickLayout('List view')
    expect(grid().restoreRequest).toBeDefined()

    scrollWindowTo(SCROLL_Y + 800)

    expect(block).not.toHaveAttribute('data-scroll-hidden')
  })

  it('test_scroll_capture_is_blocked_while_a_switch_is_pending_and_resumes_after_landing', () => {
    mount({ first: 6 })
    clickLayout('List view')
    updateView.mockClear()

    scrollWindowTo(SCROLL_Y + 30)
    expect(updateView).not.toHaveBeenCalled()

    act(() => grid().onRestoreApplied?.(grid().restoreRequest as RestoreRequest))
    updateView.mockClear()
    scrollWindowTo(scrollY + 30)
    expect(updateView).toHaveBeenCalled()
  })

  it('test_switch_at_the_top_of_the_page_uses_the_real_rect_and_issues_no_scroll', () => {
    mount({ stuck: false, first: 0 })
    model.tops.set(IDS[0], 140)

    clickLayout('List view')

    expect(grid().restoreRequest).toBeUndefined()
    expect(scrollTo).not.toHaveBeenCalled()
    // Not stuck: the offset is where the card really is, not under the bar.
    expect(checkpoint.mock.calls[0][0].anchor).toMatchObject({ itemId: IDS[0], offset: 140 })
    expect(checkpoint.mock.calls[0][0].layout.mode).toBe('list')
  })

  it('test_switch_to_the_same_layout_is_a_no_op', () => {
    mount({ first: 6 })

    clickLayout('Grid view')

    expect(checkpoint).not.toHaveBeenCalled()
    expect(grid().restoreRequest).toBeUndefined()
  })

  it('test_reclick_while_pending_keeps_the_first_anchor', () => {
    mount({ first: 6 })
    clickLayout('List view')
    // Mid-transition the layout reads differently: a fresh measure would pick card 9.
    setTops(IDS, 9)
    reportVisibleStart(9, 3)

    clickLayout('Grid view')

    expect(checkpoint).toHaveBeenCalledTimes(2)
    expect(checkpoint.mock.calls[1][0].anchor.itemId).toBe(IDS[6])
    expect(grid().restoreRequest).toEqual({ key: 'layout-switch:2', index: 6 })
  })
})

describe('Library layout switch pending-state hygiene', () => {
  it('test_refresh_replacing_the_list_while_pending_lands_on_the_same_card_by_id', () => {
    const { view } = mount({ first: 6 })
    clickLayout('List view')
    expect(grid().restoreRequest?.index).toBe(6)

    // A refresh puts three new galleries in front: card 7 is now at index 9.
    const refreshed = [201, 202, 203, ...IDS]
    setIds(refreshed)
    setTops(refreshed, 9)
    view.rerender(<LibraryPage />)

    expect(grid().restoreRequest).toEqual({ key: 'layout-switch:1', index: 9 })
    model.tops.set(IDS[6], 300)
    model.tops.set(IDS[3], 40)
    act(() => grid().onRestoreApplied?.(grid().restoreRequest as RestoreRequest))
    expect(scrollTo).toHaveBeenCalledWith(0, SCROLL_Y + 300 - (BAR_BOTTOM + GAP))
  })

  it('test_stale_index_reported_after_a_refresh_never_lands_on_another_card', () => {
    const { view } = mount({ first: 6 })
    clickLayout('List view')
    const stale = grid().restoreRequest as RestoreRequest
    const refreshed = [201, 202, 203, ...IDS]
    setIds(refreshed)
    setTops(refreshed, 9)
    view.rerender(<LibraryPage />)
    scrollTo.mockClear()

    // Index 6 now holds a different gallery.
    act(() => grid().onRestoreApplied?.(stale))

    expect(scrollTo).not.toHaveBeenCalled()
    expect(grid().restoreRequest).toBeUndefined()
  })

  it('test_id_gone_from_the_list_clears_the_channel_and_capture_resumes', () => {
    const { view } = mount({ first: 6 })
    clickLayout('List view')
    expect(grid().restoreRequest).toBeDefined()

    const without = IDS.filter((id) => id !== IDS[6])
    setIds(without)
    setTops(without, 6)
    view.rerender(<LibraryPage />)

    expect(grid().restoreRequest).toBeUndefined()
    updateView.mockClear()
    scrollWindowTo(SCROLL_Y + 20)
    expect(updateView).toHaveBeenCalled()
  })

  it('test_identity_change_while_pending_clears_the_channel', () => {
    const { view } = mount({ first: 6 })
    clickLayout('List view')
    expect(grid().restoreRequest).toBeDefined()

    model.identityKey = 'library:B'
    view.rerender(<LibraryPage />)

    expect(grid().restoreRequest).toBeUndefined()
  })

  it('test_landing_with_no_registered_element_clears_instead_of_scrolling', () => {
    mount({ first: 6 })
    clickLayout('List view')
    const request = grid().restoreRequest as RestoreRequest
    // The anchor card unmounts before the grid reports the token applied.
    act(() => {
      grid().onRegisterElement?.(request.index, null)
    })

    act(() => grid().onRestoreApplied?.(request))

    expect(scrollTo).not.toHaveBeenCalled()
    expect(grid().restoreRequest).toBeUndefined()
  })

  it('test_watchdog_clears_a_switch_that_never_lands_after_two_seconds_and_capture_resumes', () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    mount({ first: 6 })
    clickLayout('List view')
    expect(grid().restoreRequest).toBeDefined()

    act(() => {
      vi.advanceTimersByTime(1999)
    })
    expect(grid().restoreRequest).toBeDefined()
    act(() => {
      vi.advanceTimersByTime(1)
    })

    expect(grid().restoreRequest).toBeUndefined()
    updateView.mockClear()
    scrollWindowTo(SCROLL_Y + 20)
    expect(updateView).toHaveBeenCalled()
  })

  it.each(['touchstart', 'wheel'])(
    'test_user_%s_while_pending_clears_the_switch_and_capture_resumes',
    (type) => {
      mount({ first: 6 })
      clickLayout('List view')
      expect(grid().restoreRequest).toBeDefined()

      act(() => {
        window.dispatchEvent(new Event(type))
      })

      expect(grid().restoreRequest).toBeUndefined()
      updateView.mockClear()
      scrollWindowTo(SCROLL_Y + 20)
      expect(updateView).toHaveBeenCalled()
    },
  )
})

describe('Library layout switch vs a pending session restore', () => {
  const restoreKey = 'library:restore:1'
  function pendingRestore() {
    model.restoreInstruction = {
      key: restoreKey,
      identityKey: 'library:A',
      target: {
        kind: 'view',
        view: { anchor: { itemId: IDS[4], offset: 40, scrollY: 700 }, layout: null },
      },
    }
  }

  it('test_switch_during_a_pending_session_restore_does_not_replace_the_restore_request', () => {
    pendingRestore()
    mount({ first: 6 })
    const before = grid().restoreRequest
    expect(before).toMatchObject({ key: restoreKey, index: 4 })

    clickLayout('List view')

    expect(grid().restoreRequest).toEqual(before)
    expect(grid().restoreRequest?.key).not.toMatch(/^layout-switch/)
    // The preference still changes: the restore finishes in the new layout.
    expect(localStorage.getItem('library_view_mode')).toBe('list')
    expect(grid().columns).toEqual({ base: 1 })
  })

  it('test_switch_during_a_pending_session_restore_saves_no_view', () => {
    pendingRestore()
    mount({ first: 6 })

    clickLayout('List view')

    expect(updateView).not.toHaveBeenCalled()
    expect(checkpoint).not.toHaveBeenCalled()
  })
})

describe('Library search block focus handling', () => {
  it('test_popup_focus_through_the_portal_does_not_lock_the_reveal', async () => {
    const { block } = mount({ first: 6 })
    fireEvent.click(screen.getByTestId('library-density-button'))
    const dialog = await screen.findByRole('dialog')
    // Base UI moves focus into the popup, which React reports through the portal.
    await waitFor(() => {
      flush()
      expect(dialog.contains(document.activeElement)).toBe(true)
    })

    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() =>
      expect(screen.getByTestId('library-density-button')).toHaveAttribute(
        'aria-expanded',
        'false',
      ),
    )
    scrollWindowTo(SCROLL_Y + 400)

    expect(block).toHaveAttribute('data-scroll-hidden', 'true')
  })

  it('test_focus_inside_the_search_block_still_locks_the_reveal', () => {
    const { block } = mount({ first: 6 })

    act(() => {
      screen.getByRole('textbox').focus()
    })
    scrollWindowTo(SCROLL_Y + 400)

    expect(block).not.toHaveAttribute('data-scroll-hidden')
  })
})
