import useSWR, { mutate as globalMutate } from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

/**
 * Collections list. When `galleryId` is given each collection also carries
 * `contains_gallery`. The membership-aware key still starts with
 * `'collections'`, so prefix invalidation (WS bridge, `revalidateCollections`)
 * covers both variants.
 */
export function useCollections(enabled = true, galleryId?: number) {
  const key = !enabled
    ? null
    : galleryId === undefined
      ? 'collections'
      : (['collections', 'gallery', galleryId] as const)
  return useSWR(
    key,
    () =>
      galleryId === undefined
        ? api.collections.list()
        : api.collections.list({ gallery_id: galleryId }),
    {
      // WebSocket events are best-effort and are not replayed after reconnect.
      revalidateOnFocus: true,
    },
  )
}

/**
 * Revalidate every cache entry that depends on collection membership: the
 * collections list (all variants) and the open collection pages. Both
 * `'collections'` and `'collection'` keys share the `'collection'` prefix.
 */
export function revalidateCollections() {
  return globalMutate(
    (key) =>
      (typeof key === 'string' && key.startsWith('collection')) ||
      (Array.isArray(key) && typeof key[0] === 'string' && key[0].startsWith('collection')),
  )
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
