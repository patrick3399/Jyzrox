/**
 * useCollections — Vitest test suite
 *
 * Covers:
 *   useCollections — passes key 'collections' to useSWR
 *   useCollections — fetcher calls api.collections.list
 *   useCollection  — passes null key when id is null
 *   useCollection  — passes array key with id and page when id is provided
 *   useCollection  — fetcher calls api.collections.get with id and params
 *   useCollection  — configures revalidateOnFocus: false
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockList, mockGet } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockGet: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    collections: {
      list: mockList,
      get: mockGet,
    },
  },
}))

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

import { useCollections, useCollection } from '@/hooks/useCollections'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockList.mockResolvedValue({ collections: [] })
  mockGet.mockResolvedValue({ id: 1, name: 'Test', galleries: [] })
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
