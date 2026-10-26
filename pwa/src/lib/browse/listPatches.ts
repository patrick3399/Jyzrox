import {
  createBrowseSnapshotStore,
  snapshotStorageKey,
  type BrowseSnapshotScope,
} from './snapshotStore'
import type { BrowseListPatch } from './patch'

type PatchListener = (patch: BrowseListPatch<unknown>) => void

// Mounted browse sessions, by storage object and partition key.
const listeners = new WeakMap<Storage, Map<string, Set<PatchListener>>>()

/** Receive every patch published for this partition while subscribed. */
export function subscribeBrowseListPatches<Item>(
  storage: Storage,
  scope: BrowseSnapshotScope,
  listener: (patch: BrowseListPatch<Item>) => void,
): () => void {
  const key = snapshotStorageKey(scope)
  const byKey = listeners.get(storage) ?? new Map<string, Set<PatchListener>>()
  listeners.set(storage, byKey)
  const subscribed = byKey.get(key) ?? new Set<PatchListener>()
  byKey.set(key, subscribed)
  const entry = listener as unknown as PatchListener
  subscribed.add(entry)
  return () => {
    subscribed.delete(entry)
    if (subscribed.size === 0 && byKey.get(key) === subscribed) byKey.delete(key)
  }
}

export type PublishBrowseListPatchOptions<Item> = {
  storage: Storage
  scope: BrowseSnapshotScope
  patch: BrowseListPatch<Item>
  /** The source's item validator: a partition that fails it is dropped, as
   *  the list itself would drop it on restore. */
  validateItem?: (value: unknown) => boolean
}

/**
 * Apply `patch` to the saved lists of one partition, then to every list of
 * that partition mounted in this document. Saved lists come first, so a list
 * that restores after this call reads the patched snapshot and one already
 * mounted gets the patch from its listener.
 */
export function publishBrowseListPatch<Item>({
  storage,
  scope,
  patch,
  validateItem,
}: PublishBrowseListPatchOptions<Item>): void {
  createBrowseSnapshotStore<Item, unknown>({ storage, scope, validateItem }).patchItems(patch)
  const subscribed = listeners.get(storage)?.get(snapshotStorageKey(scope))
  if (!subscribed) return
  for (const listener of [...subscribed]) {
    listener(patch as unknown as BrowseListPatch<unknown>)
  }
}
