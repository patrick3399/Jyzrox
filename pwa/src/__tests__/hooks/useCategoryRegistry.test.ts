import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockList, mockUseSWR } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockUseSWR: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  api: { galleryCategories: { list: mockList } },
}))

vi.mock('swr', () => ({ default: mockUseSWR }))

import { useCategoryRegistry } from '@/hooks/useCategoryRegistry'

beforeEach(() => {
  vi.clearAllMocks()
  mockUseSWR.mockReturnValue({ data: undefined })
  mockList.mockResolvedValue({ categories: [], palette: [] })
})

describe('useCategoryRegistry', () => {
  it('test_useCategoryRegistry_key_isGalleryCategories', () => {
    useCategoryRegistry()
    expect(mockUseSWR.mock.calls[0][0]).toBe('gallery-categories')
  })

  it('test_useCategoryRegistry_fetcher_callsApiGalleryCategoriesList', async () => {
    useCategoryRegistry()
    const fetcher = mockUseSWR.mock.calls[0][1] as () => Promise<unknown>
    await fetcher()
    expect(mockList).toHaveBeenCalledTimes(1)
  })
})
