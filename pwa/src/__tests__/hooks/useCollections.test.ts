/**
 * useCollections — Vitest test suite
 *
 * Covers:
 *   useCollections              — passes key 'collections' to useSWR
 *   useCollections              — fetcher calls api.collections.list
 *   useCollection               — passes null key when id is null
 *   useCollection               — passes array key with id and page when id is provided
 *   useCollection               — fetcher calls api.collections.get with id and params
 *   useCollection               — configures revalidateOnFocus: false
 *   useCreateCollection         — key is 'collections', trigger calls api.collections.create
 *   useUpdateCollection         — key is 'collections', trigger calls api.collections.update
 *   useDeleteCollection         — key is 'collections', trigger calls api.collections.delete
 *   useAddGalleriesToCollection — key is 'collections', trigger calls api.collections.addGalleries
 *   useRemoveGalleryFromCollection — key is 'collections', trigger calls api.collections.removeGallery
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockList, mockGet, mockCreate, mockUpdate, mockDelete, mockAddGalleries, mockRemoveGallery } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockGet: vi.fn(),
  mockCreate: vi.fn(),
  mockUpdate: vi.fn(),
  mockDelete: vi.fn(),
  mockAddGalleries: vi.fn(),
  mockRemoveGallery: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    collections: {
      list: mockList,
      get: mockGet,
      create: mockCreate,
      update: mockUpdate,
      delete: mockDelete,
      addGalleries: mockAddGalleries,
      removeGallery: mockRemoveGallery,
    },
  },
}))

// ── swr/mutation mock ─────────────────────────────────────────────────

interface SwrMutationCall {
  key: unknown
  fetcher: ((_k: unknown, extra: { arg: unknown }) => unknown)
}

const swrMutationCalls: SwrMutationCall[] = []

const { mockUseSWRMutation } = vi.hoisted(() => ({
  mockUseSWRMutation: vi.fn(
    (key: unknown, fetcher: (_k: unknown, extra: { arg: unknown }) => unknown) => {
      swrMutationCalls.push({ key, fetcher })
      return {
        trigger: (arg: unknown) => fetcher(key, { arg }),
        isMutating: false,
      }
    },
  ),
}))

vi.mock('swr/mutation', () => ({ default: mockUseSWRMutation }))

// ── swr mock ─────────────────────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

const { mockUseSWR } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: true, error: undefined }
    },
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

// ── Import hooks after mocks ──────────────────────────────────────────

import {
  useCollections,
  useCollection,
  useCreateCollection,
  useUpdateCollection,
  useDeleteCollection,
  useAddGalleriesToCollection,
  useRemoveGalleryFromCollection,
} from '@/hooks/useCollections'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  swrMutationCalls.length = 0
  mockList.mockResolvedValue({ collections: [] })
  mockGet.mockResolvedValue({ id: 1, name: 'Test', galleries: [] })
  mockCreate.mockResolvedValue({ id: 2, name: 'New' })
  mockUpdate.mockResolvedValue({ id: 2, name: 'Updated' })
  mockDelete.mockResolvedValue(undefined)
  mockAddGalleries.mockResolvedValue(undefined)
  mockRemoveGallery.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useCollections', () => {
  it('test_useCollections_key_passesCollectionsStringToSwr', () => {
    useCollections()
    expect(lastSwrCall().key).toBe('collections')
  })

  it('test_useCollections_fetcher_callsApiCollectionsList', async () => {
    useCollections()
    await lastSwrCall().fetcher!()
    expect(mockList).toHaveBeenCalledOnce()
  })
})

describe('useCollection', () => {
  it('test_useCollection_nullId_passesNullKeyToSwr', () => {
    useCollection(null)
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useCollection_validId_passesArrayKeyWithIdAndPage', () => {
    useCollection(5)
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('collection')
    expect((key as unknown[])[1]).toBe(5)
  })

  it('test_useCollection_validId_pageDefaultsToZeroInKey', () => {
    useCollection(3)
    const { key } = lastSwrCall()
    expect((key as unknown[])[2]).toBe(0)
  })

  it('test_useCollection_validId_fetcher_callsApiCollectionsGet', async () => {
    useCollection(7, { page: 2, limit: 20 })
    await lastSwrCall().fetcher!()
    expect(mockGet).toHaveBeenCalledWith(7, { page: 2, limit: 20 })
  })

  it('test_useCollection_options_setsRevalidateOnFocusFalse', () => {
    useCollection(1)
    expect(lastSwrCall().options.revalidateOnFocus).toBe(false)
  })
})

// ── Mutation hooks ────────────────────────────────────────────────────

function lastMutationCall(): SwrMutationCall {
  return swrMutationCalls[swrMutationCalls.length - 1]
}

describe('useCreateCollection', () => {
  it('test_useCreateCollection_key_isCollectionsString', () => {
    useCreateCollection()
    expect(lastMutationCall().key).toBe('collections')
  })

  it('test_useCreateCollection_trigger_callsApiCollectionsCreate', async () => {
    const { trigger } = useCreateCollection()
    const arg = { name: 'My Collection', description: 'desc' }
    await trigger(arg)
    expect(mockCreate).toHaveBeenCalledWith(arg)
  })
})

describe('useUpdateCollection', () => {
  it('test_useUpdateCollection_key_isCollectionsString', () => {
    useUpdateCollection()
    expect(lastMutationCall().key).toBe('collections')
  })

  it('test_useUpdateCollection_trigger_callsApiCollectionsUpdateWithIdAndData', async () => {
    const { trigger } = useUpdateCollection()
    const arg = { id: 5, data: { name: 'Renamed', cover_gallery_id: 10 } }
    await trigger(arg)
    expect(mockUpdate).toHaveBeenCalledWith(5, { name: 'Renamed', cover_gallery_id: 10 })
  })
})

describe('useDeleteCollection', () => {
  it('test_useDeleteCollection_key_isCollectionsString', () => {
    useDeleteCollection()
    expect(lastMutationCall().key).toBe('collections')
  })

  it('test_useDeleteCollection_trigger_callsApiCollectionsDeleteWithId', async () => {
    const { trigger } = useDeleteCollection()
    await trigger(7)
    expect(mockDelete).toHaveBeenCalledWith(7)
  })
})

describe('useAddGalleriesToCollection', () => {
  it('test_useAddGalleriesToCollection_key_isCollectionsString', () => {
    useAddGalleriesToCollection()
    expect(lastMutationCall().key).toBe('collections')
  })

  it('test_useAddGalleriesToCollection_trigger_callsApiCollectionsAddGalleriesWithIdAndGalleryIds', async () => {
    const { trigger } = useAddGalleriesToCollection()
    const arg = { id: 3, galleryIds: [10, 20, 30] }
    await trigger(arg)
    expect(mockAddGalleries).toHaveBeenCalledWith(3, [10, 20, 30])
  })
})

describe('useRemoveGalleryFromCollection', () => {
  it('test_useRemoveGalleryFromCollection_key_isCollectionsString', () => {
    useRemoveGalleryFromCollection()
    expect(lastMutationCall().key).toBe('collections')
  })

  it('test_useRemoveGalleryFromCollection_trigger_callsApiCollectionsRemoveGalleryWithBothIds', async () => {
    const { trigger } = useRemoveGalleryFromCollection()
    const arg = { collectionId: 3, galleryId: 99 }
    await trigger(arg)
    expect(mockRemoveGallery).toHaveBeenCalledWith(3, 99)
  })
})
