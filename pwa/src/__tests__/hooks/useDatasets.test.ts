import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  addMembers: vi.fn(),
  excludeImage: vi.fn(),
  previewFilters: vi.fn(),
  applyFilters: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ api: { datasets: apiMocks } }))

const swrCalls: Array<{
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}> = []
vi.mock('swr', () => ({
  default: (
    key: unknown,
    fetcher: (() => unknown) | null,
    options: Record<string, unknown> = {},
  ) => {
    swrCalls.push({ key, fetcher, options })
    return { data: undefined, isLoading: true }
  },
}))

const mutationCalls: Array<{
  key: unknown
  fetcher: (_key: unknown, extra: { arg: never }) => unknown
}> = []
vi.mock('swr/mutation', () => ({
  default: (key: unknown, fetcher: (_key: unknown, extra: { arg: never }) => unknown) => {
    mutationCalls.push({ key, fetcher })
    return { trigger: (arg: never) => fetcher(key, { arg }) }
  },
}))

import {
  useAddDatasetMembers,
  useApplyDatasetFilters,
  useCreateDataset,
  useDataset,
  useDatasets,
  useDeleteDataset,
  useExcludeDatasetImage,
  usePreviewDatasetFilters,
  useUpdateDataset,
} from '@/hooks/useDatasets'

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mutationCalls.length = 0
})

describe('dataset hooks', () => {
  it('lists datasets and loads a state-specific detail page', async () => {
    useDatasets()
    expect(swrCalls[0].key).toBe('datasets')
    await swrCalls[0].fetcher?.()
    expect(apiMocks.list).toHaveBeenCalledOnce()

    useDataset(8, { state: 'excluded', page: 2, limit: 48 })
    expect(swrCalls[1].key).toEqual(['dataset', 8, 'excluded', 2])
    expect(swrCalls[1].options.revalidateOnFocus).toBe(false)
    await swrCalls[1].fetcher?.()
    expect(apiMocks.get).toHaveBeenCalledWith(8, { state: 'excluded', page: 2, limit: 48 })
  })

  it('disables dataset listing for roles that cannot manage datasets', () => {
    useDatasets(false)
    expect(swrCalls[0].key).toBeNull()
  })

  it('disables detail fetching without an ID', () => {
    useDataset(null)
    expect(swrCalls[0].key).toBeNull()
  })

  it('wires every dataset mutation to the API client', async () => {
    const create = useCreateDataset().trigger
    const update = useUpdateDataset().trigger
    const remove = useDeleteDataset().trigger
    const add = useAddDatasetMembers().trigger
    const exclude = useExcludeDatasetImage().trigger
    const preview = usePreviewDatasetFilters().trigger
    const apply = useApplyDatasetFilters().trigger

    await create({ name: 'Set', gallery_ids: [1] })
    await update({ id: 2, data: { name: 'Renamed' } })
    await remove(2)
    await add({ id: 2, selection: { image_ids: [9] } })
    await exclude({ id: 2, imageId: 9 })
    await preview({
      id: 2,
      filters: { min_width: 1024, min_height: 1024, max_aspect_ratio: 4 },
    })
    await apply({
      id: 2,
      filters: { min_width: null, min_height: null, max_aspect_ratio: null },
    })

    expect(apiMocks.create).toHaveBeenCalledWith({ name: 'Set', gallery_ids: [1] })
    expect(apiMocks.update).toHaveBeenCalledWith(2, { name: 'Renamed' })
    expect(apiMocks.delete).toHaveBeenCalledWith(2)
    expect(apiMocks.addMembers).toHaveBeenCalledWith(2, { image_ids: [9] })
    expect(apiMocks.excludeImage).toHaveBeenCalledWith(2, 9)
    expect(apiMocks.previewFilters).toHaveBeenCalledWith(2, {
      min_width: 1024,
      min_height: 1024,
      max_aspect_ratio: 4,
    })
    expect(apiMocks.applyFilters).toHaveBeenCalledWith(2, {
      min_width: null,
      min_height: null,
      max_aspect_ratio: null,
    })
    expect(mutationCalls.every((call) => call.key === 'datasets')).toBe(true)
  })
})
