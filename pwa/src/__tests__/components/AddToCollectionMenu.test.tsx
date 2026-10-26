import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { Collection } from '@/lib/types'

const h = vi.hoisted(() => ({
  collections: [] as Collection[],
  swrKeys: [] as unknown[],
  mockMutate: vi.fn(),
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockAddGalleries: vi.fn(),
  mockRemoveGallery: vi.fn(),
  mockBatch: vi.fn(),
  toastSuccess: vi.fn(),
  toastWarning: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('swr', () => ({
  default: (key: unknown, fetcher: (() => unknown) | null) => {
    h.swrKeys.push(key)
    // Exercise the fetcher so the gallery_id wiring is observable.
    if (key && fetcher) void fetcher()
    return { data: key ? { collections: h.collections } : undefined, isLoading: false }
  },
  mutate: h.mockMutate,
}))

vi.mock('@/lib/api', () => ({
  api: {
    collections: {
      list: h.mockList,
      create: h.mockCreate,
      addGalleries: h.mockAddGalleries,
      removeGallery: h.mockRemoveGallery,
    },
    library: { batchGalleries: h.mockBatch },
  },
}))

vi.mock('sonner', () => ({
  toast: { success: h.toastSuccess, warning: h.toastWarning, error: h.toastError },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}|${Object.values(params).join(',')}` : key,
}))

import { AddToCollectionMenu } from '@/components/library/AddToCollectionMenu'

function makeCollection(over: Partial<Collection>): Collection {
  return {
    id: 1,
    name: 'Favorites',
    description: null,
    cover_gallery_id: null,
    gallery_count: 0,
    cover_thumb: null,
    created_at: null,
    updated_at: null,
    ...over,
  }
}

function openMenu() {
  fireEvent.click(screen.getByRole('button', { name: 'collections.addToCollection' }))
}

beforeEach(() => {
  vi.clearAllMocks()
  h.collections = []
  h.swrKeys = []
  h.mockList.mockResolvedValue({ collections: [] })
  h.mockMutate.mockResolvedValue(undefined)
  h.mockCreate.mockResolvedValue({ id: 99, name: 'Brand new' })
  h.mockAddGalleries.mockResolvedValue({ status: 'ok', added: 1, denied: [] })
  h.mockRemoveGallery.mockResolvedValue({ status: 'ok' })
  h.mockBatch.mockResolvedValue({ status: 'ok', affected: 2, denied: [] })
})

describe('AddToCollectionMenu', () => {
  it('test_addToCollectionMenu_zeroCollections_stillRendersCreateInput', () => {
    render(<AddToCollectionMenu galleryIds={[1, 2]} />)
    openMenu()

    expect(screen.getByPlaceholderText('collections.newCollection')).toBeInTheDocument()
    expect(screen.getByText('collections.noCollections')).toBeInTheDocument()
  })

  it('test_addToCollectionMenu_singleMode_zeroCollections_stillRendersCreateInput', () => {
    render(<AddToCollectionMenu galleryId={5} />)
    openMenu()

    expect(screen.getByPlaceholderText('collections.newCollection')).toBeInTheDocument()
  })

  it('test_addToCollectionMenu_singleMode_requestsMembershipForGalleryId', () => {
    render(<AddToCollectionMenu galleryId={5} />)
    openMenu()

    expect(h.swrKeys).toContainEqual(['collections', 'gallery', 5])
    expect(h.mockList).toHaveBeenCalledWith({ gallery_id: 5 })
  })

  it('test_addToCollectionMenu_createAndAdd_batchMode_createsThenAddsWithNewId', async () => {
    const onChanged = vi.fn()
    render(<AddToCollectionMenu galleryIds={[10, 11]} onChanged={onChanged} />)
    openMenu()

    fireEvent.change(screen.getByPlaceholderText('collections.newCollection'), {
      target: { value: '  Brand new ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'collections.createAndAdd' }))

    await waitFor(() => expect(h.mockBatch).toHaveBeenCalled())
    expect(h.mockCreate).toHaveBeenCalledWith({ name: 'Brand new' })
    expect(h.mockBatch).toHaveBeenCalledWith({
      action: 'add_to_collection',
      gallery_ids: [10, 11],
      collection_id: 99,
    })
    expect(h.mockCreate.mock.invocationCallOrder[0]).toBeLessThan(
      h.mockBatch.mock.invocationCallOrder[0],
    )
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('test_addToCollectionMenu_createAndAdd_singleMode_addsGalleryToNewCollection', async () => {
    render(<AddToCollectionMenu galleryId={5} />)
    openMenu()

    const input = screen.getByPlaceholderText('collections.newCollection')
    fireEvent.change(input, { target: { value: 'Brand new' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    await waitFor(() => expect(h.mockAddGalleries).toHaveBeenCalledWith(99, [5]))
    expect(h.mockCreate).toHaveBeenCalledWith({ name: 'Brand new' })
  })

  it('test_addToCollectionMenu_createFailure_doesNotCallAdd', async () => {
    h.mockCreate.mockRejectedValue(new Error('boom'))
    render(<AddToCollectionMenu galleryId={5} />)
    openMenu()

    fireEvent.change(screen.getByPlaceholderText('collections.newCollection'), {
      target: { value: 'x' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'collections.createAndAdd' }))

    await waitFor(() => expect(h.toastError).toHaveBeenCalledWith('collections.createFailed'))
    expect(h.mockAddGalleries).not.toHaveBeenCalled()
  })

  it('test_addToCollectionMenu_singleMode_containsGallery_clickCallsRemove', async () => {
    h.collections = [makeCollection({ id: 7, name: 'Has it', contains_gallery: true })]
    render(<AddToCollectionMenu galleryId={5} />)
    openMenu()

    fireEvent.click(screen.getByRole('button', { name: /Has it/ }))

    await waitFor(() => expect(h.mockRemoveGallery).toHaveBeenCalledWith(7, 5))
    expect(h.mockAddGalleries).not.toHaveBeenCalled()
  })

  it('test_addToCollectionMenu_singleMode_notContained_clickCallsAdd', async () => {
    h.collections = [makeCollection({ id: 8, name: 'Lacks it', contains_gallery: false })]
    render(<AddToCollectionMenu galleryId={5} />)
    openMenu()

    fireEvent.click(screen.getByRole('button', { name: /Lacks it/ }))

    await waitFor(() => expect(h.mockAddGalleries).toHaveBeenCalledWith(8, [5]))
    expect(h.mockRemoveGallery).not.toHaveBeenCalled()
  })

  it('test_addToCollectionMenu_batchMode_hasNoCheckMarks', () => {
    h.collections = [makeCollection({ id: 7, name: 'Has it', contains_gallery: true })]
    render(<AddToCollectionMenu galleryIds={[1, 2]} />)
    openMenu()

    expect(screen.queryByLabelText('collections.inCollection')).not.toBeInTheDocument()
  })

  it('test_addToCollectionMenu_afterAdd_revalidatesCollectionsKey', async () => {
    h.collections = [makeCollection({ id: 7, name: 'Target' })]
    render(<AddToCollectionMenu galleryIds={[1, 2]} />)
    openMenu()

    fireEvent.click(screen.getByRole('button', { name: /Target/ }))

    await waitFor(() => expect(h.mockMutate).toHaveBeenCalled())
    const filter = h.mockMutate.mock.calls[0][0] as (key: unknown) => boolean
    expect(filter('collections')).toBe(true)
    expect(filter(['collections', 'gallery', 5])).toBe(true)
    expect(filter(['collection', 7, 0])).toBe(true)
    expect(filter('library/galleries')).toBe(false)
  })

  it('test_addToCollectionMenu_deniedNonEmpty_showsWarningToastWithCount', async () => {
    h.collections = [makeCollection({ id: 7, name: 'Target' })]
    h.mockBatch.mockResolvedValue({ status: 'ok', affected: 1, denied: [3, 4] })
    render(<AddToCollectionMenu galleryIds={[1, 2, 3, 4]} />)
    openMenu()

    fireEvent.click(screen.getByRole('button', { name: /Target/ }))

    await waitFor(() => expect(h.toastWarning).toHaveBeenCalledWith('collections.addDenied|2'))
    expect(h.mockBatch).toHaveBeenCalledWith({
      action: 'add_to_collection',
      gallery_ids: [1, 2, 3, 4],
      collection_id: 7,
    })
  })

  // Regression: the sheet closed on a document-level Escape, but the event went
  // on to the detail page's window-level shortcut, which took the same Escape
  // as "go back" — closing the sheet also left the page.
  it('test_addToCollectionMenu_escapeWhileOpen_closesWithoutReachingWindowShortcuts', () => {
    render(<AddToCollectionMenu galleryId={5} />)
    openMenu()
    const windowSaw = vi.fn()
    window.addEventListener('keydown', windowSaw)
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    try {
      fireEvent(document.body, event)
    } finally {
      window.removeEventListener('keydown', windowSaw)
    }

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(windowSaw).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(true)
  })

  it('test_addToCollectionMenu_escapeWhileClosed_leavesTheKeyAlone', () => {
    render(<AddToCollectionMenu galleryId={5} />)
    const windowSaw = vi.fn()
    window.addEventListener('keydown', windowSaw)
    try {
      fireEvent.keyDown(document.body, { key: 'Escape' })
    } finally {
      window.removeEventListener('keydown', windowSaw)
    }

    expect(windowSaw).toHaveBeenCalledTimes(1)
  })

  it('test_addToCollectionMenu_openAndClose_reportedThroughOnOpenChange', () => {
    const onOpenChange = vi.fn()
    render(<AddToCollectionMenu galleryId={5} onOpenChange={onOpenChange} />)

    openMenu()
    expect(onOpenChange).toHaveBeenLastCalledWith(true)

    fireEvent.click(screen.getByRole('button', { name: 'common.close' }))
    expect(onOpenChange).toHaveBeenLastCalledWith(false)

    openMenu()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onOpenChange).toHaveBeenLastCalledWith(false)
  })
})
