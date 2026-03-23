import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useCollections() {
  return useSWR('collections', () => api.collections.list())
}

export function useCollection(id: number | null, params: { page?: number; limit?: number } = {}) {
  return useSWR(
    id ? ['collection', id, params.page ?? 0] : null,
    () => api.collections.get(id!, params),
    { revalidateOnFocus: false },
  )
}

export function useCreateCollection() {
  return useSWRMutation(
    'collections',
    (_key: unknown, { arg }: { arg: { name: string; description?: string } }) =>
      api.collections.create(arg),
  )
}

export function useUpdateCollection() {
  return useSWRMutation(
    'collections',
    (_key: unknown, { arg }: { arg: { id: number; data: { name?: string; description?: string; cover_gallery_id?: number } } }) =>
      api.collections.update(arg.id, arg.data),
  )
}

export function useDeleteCollection() {
  return useSWRMutation(
    'collections',
    (_key: unknown, { arg }: { arg: number }) =>
      api.collections.delete(arg),
  )
}

export function useAddGalleriesToCollection() {
  return useSWRMutation(
    'collections',
    (_key: unknown, { arg }: { arg: { id: number; galleryIds: number[] } }) =>
      api.collections.addGalleries(arg.id, arg.galleryIds),
  )
}

export function useRemoveGalleryFromCollection() {
  return useSWRMutation(
    'collections',
    (_key: unknown, { arg }: { arg: { collectionId: number; galleryId: number } }) =>
      api.collections.removeGallery(arg.collectionId, arg.galleryId),
  )
}
