import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'
import type { DatasetSelection } from '@/lib/types'

export function useDatasets() {
  return useSWR('datasets', () => api.datasets.list())
}

export function useDataset(
  id: number | null,
  params: { state?: 'included' | 'excluded'; page?: number; limit?: number } = {},
) {
  return useSWR(
    id ? ['dataset', id, params.state ?? 'included', params.page ?? 0] : null,
    () => api.datasets.get(id!, params),
    { revalidateOnFocus: false },
  )
}

export function useCreateDataset() {
  return useSWRMutation(
    'datasets',
    (_key: unknown, { arg }: { arg: { name: string; description?: string } & DatasetSelection }) =>
      api.datasets.create(arg),
  )
}

export function useUpdateDataset() {
  return useSWRMutation(
    'datasets',
    (
      _key: unknown,
      { arg }: { arg: { id: number; data: { name?: string; description?: string | null } } },
    ) => api.datasets.update(arg.id, arg.data),
  )
}

export function useDeleteDataset() {
  return useSWRMutation('datasets', (_key: unknown, { arg }: { arg: number }) =>
    api.datasets.delete(arg),
  )
}

export function useAddDatasetMembers() {
  return useSWRMutation(
    'datasets',
    (_key: unknown, { arg }: { arg: { id: number; selection: DatasetSelection } }) =>
      api.datasets.addMembers(arg.id, arg.selection),
  )
}

export function useExcludeDatasetImage() {
  return useSWRMutation(
    'datasets',
    (_key: unknown, { arg }: { arg: { id: number; imageId: number } }) =>
      api.datasets.excludeImage(arg.id, arg.imageId),
  )
}
