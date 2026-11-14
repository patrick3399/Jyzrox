/**
 * Library select mode must not remount the gallery cards.
 *
 * renderItem used to wrap the card in an extra <div> only while select mode was
 * on. The root element type changed (<Card> ↔ <div>), so React threw away every
 * visible card and rebuilt it: each thumbnail <img> was recreated, decoded again
 * and the whole grid flashed on both entering and leaving select mode.
 *
 * Harness mirrors library-batch-tag-dialog.test.tsx, with real select-mode state
 * and a grid mock that actually calls renderItem.
 */
import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  mounts: 0,
  items: [] as Array<Record<string, unknown>>,
}))

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: h.push }) }))
vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string, params?: Record<string, string | number>) =>
    params ? `${key} ${Object.values(params).join(' ')}` : key,
}))
vi.mock('@/hooks/useUnifiedSearch', () => ({
  useUnifiedSearch: () => {
    const [selectMode, setSelectMode] = useState(false)
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
    return {
      rawQuery: '',
      inputValue: '',
      parsed: {
        tags: [],
        nameOnlyTags: [],
        excludeTags: [],
        title: null,
        sources: [],
        excludeSources: [],
        rating: null,
        favorited: false,
        readingList: false,
        collection: null,
        artistId: null,
        categories: [],
        excludeCategories: [],
        importMode: null,
        sort: null,
      },
      setFilter: vi.fn(),
      setFacet: vi.fn(),
      commitSearch: vi.fn(),
      clearSearch: vi.fn(),
      clearFilters: vi.fn(),
      handleInputChange: vi.fn(),
      selectMode,
      setSelectMode,
      selectedIds,
      setSelectedIds,
    }
  },
}))
vi.mock('@/hooks/useLibraryBrowseSession', () => ({
  useLibraryBrowseSession: () => ({
    state: {
      identityKey: 'library:A',
      items: h.items,
      total: h.items.length,
      status: 'idle',
      error: null,
      hasMore: false,
    },
    loadMore: vi.fn(),
    refresh: vi.fn(),
    retry: vi.fn(),
    checkpoint: vi.fn(),
    updateView: vi.fn(),
    restoreInstruction: null,
    acknowledgeRestore: vi.fn(),
  }),
}))
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'member', role: 'member' } }),
}))
vi.mock('@/hooks/useLibraryFacets', () => ({
  useLibraryFacets: () => ({ data: { sources: [], categories: [], uncategorized: 0 } }),
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
vi.mock('@/components/VirtualGrid', async () => {
  const { Fragment } = await import('react')
  return {
    VirtualGrid: ({
      items,
      getItemKey,
      renderItem,
    }: {
      items: Array<{ id: number }>
      getItemKey: (item: { id: number }) => number
      renderItem: (item: { id: number }, index: number) => React.ReactNode
    }) => (
      <div>
        {items.map((item, i) => (
          <Fragment key={getItemKey(item)}>{renderItem(item, i)}</Fragment>
        ))}
      </div>
    ),
  }
})
vi.mock('@/components/GalleryCard', async () => {
  const { useEffect } = await import('react')
  return {
    LibraryGalleryCard: ({
      gallery,
      onClick,
      selected,
      selectMode,
    }: {
      gallery: { id: number }
      onClick?: () => void
      selected?: boolean
      selectMode?: boolean
    }) => {
      useEffect(() => {
        h.mounts += 1
      }, [])
      return (
        <article
          data-testid={`card-${gallery.id}`}
          data-selected={selected ? 'true' : 'false'}
          data-select-mode={selectMode ? 'true' : 'false'}
          onClick={onClick}
        >
          <img data-testid={`thumb-${gallery.id}`} alt="" />
        </article>
      )
    },
  }
})
vi.mock('@/components/GalleryListCard', () => ({ GalleryListCard: () => null }))
vi.mock('@/lib/api', () => ({ api: { library: {} } }))

import LibraryPage from '@/app/library/page'

beforeEach(() => {
  vi.clearAllMocks()
  h.mounts = 0
  h.items = [1, 2, 3].map((id) => ({
    id,
    source: 'ehentai',
    source_id: String(id),
    title: `Gallery ${id}`,
    cover_thumb: `/media/thumbs/${id}/thumb_160.webp`,
    pages: 10,
  }))
})

function expectSameThumbs(before: HTMLElement[]) {
  before.forEach((img, i) => {
    expect(img.isConnected).toBe(true)
    expect(screen.getByTestId(`thumb-${i + 1}`)).toBe(img)
  })
}

describe('Library select mode', () => {
  it('test_library_toggling_select_mode_keeps_card_thumbnails_mounted', () => {
    render(<LibraryPage />)
    const before = [1, 2, 3].map((id) => screen.getByTestId(`thumb-${id}`))
    expect(h.mounts).toBe(3)

    const selectButton = screen.getByRole('button', { name: 'library.select' })
    fireEvent.click(selectButton)
    expect(screen.getByTestId('card-1')).toHaveAttribute('data-select-mode', 'true')
    // Same <img> nodes: the cards were updated in place, not rebuilt.
    expectSameThumbs(before)

    fireEvent.click(selectButton)
    expect(screen.getByTestId('card-1')).toHaveAttribute('data-select-mode', 'false')
    expectSameThumbs(before)
    expect(h.mounts).toBe(3)
  })

  it('test_library_card_click_in_select_mode_toggles_selection_instead_of_opening', () => {
    render(<LibraryPage />)
    fireEvent.click(screen.getByRole('button', { name: 'library.select' }))

    fireEvent.click(screen.getByTestId('card-2'))
    expect(screen.getByTestId('card-2')).toHaveAttribute('data-selected', 'true')
    expect(h.push).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('card-2'))
    expect(screen.getByTestId('card-2')).toHaveAttribute('data-selected', 'false')

    // Leaving select mode restores the normal open-on-click behaviour.
    fireEvent.click(screen.getByRole('button', { name: 'library.select' }))
    fireEvent.click(screen.getByTestId('card-2'))
    expect(h.push).toHaveBeenCalledTimes(1)
  })
})
