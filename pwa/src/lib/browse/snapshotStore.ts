import { patchPages, type BrowseListPatch } from './patch'
import { parsePartition } from './snapshotParse'
import type {
  BrowseSnapshot,
  BrowseSnapshotRestore,
  BrowseSnapshotSaveOptions,
  BrowseSnapshotScope,
  StoredEntry,
  StoredPartition,
  StoreOptions,
} from './snapshotTypes'

export type {
  BrowseLayoutSnapshot,
  BrowseSnapshot,
  BrowseSnapshotMetadata,
  BrowseSnapshotRestore,
  BrowseSnapshotSaveOptions,
  BrowseSnapshotScope,
} from './snapshotTypes'
export { clearBrowseSessionStorage } from './snapshotLogout'

const DEFAULT_MAX_ENTRIES = 8
const DEFAULT_MAX_BYTES = 2_000_000

const PARTITION_HEAD = '{"version":1,"entries":['
const PARTITION_TAIL = ']}'
const PARTITION_ENVELOPE_BYTES = PARTITION_HEAD.length + PARTITION_TAIL.length
export function snapshotStorageKey(scope: BrowseSnapshotScope): string {
  return [
    'browse_session_v1',
    encodeURIComponent(scope.userId),
    encodeURIComponent(scope.tabId),
    encodeURIComponent(scope.sourceId),
    String(scope.schemaVersion),
  ].join(':')
}

function serializedBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength
}

export function createBrowseSnapshotStore<Item, Cursor>({
  storage,
  scope,
  maxEntries = DEFAULT_MAX_ENTRIES,
  maxBytes = DEFAULT_MAX_BYTES,
  now = Date.now,
  validateCursor,
  validateItem,
  validateMeta,
}: StoreOptions) {
  const storageKey = snapshotStorageKey(scope)

  function clear(): void {
    try {
      storage.removeItem(storageKey)
    } catch {
      // Storage is best effort. An inaccessible partition is equivalent to empty.
    }
  }

  function read(): StoredPartition<Item, Cursor> {
    let raw: string | null
    try {
      raw = storage.getItem(storageKey)
    } catch {
      clear()
      return { version: 1, entries: [] }
    }
    if (raw === null) return { version: 1, entries: [] }
    const parsed = parsePartition<Item, Cursor>(raw, validateCursor, validateItem, validateMeta)
    if (parsed) return parsed
    clear()
    return { version: 1, entries: [] }
  }

  /** Store `entries` (listed most valuable first) as the partition, within the
   *  byte budget and the storage quota. Reports whether it was stored; a failure
   *  leaves whatever the partition held before untouched, so callers decide what
   *  is safe to give up — one list that does not fit must not cost the others. */
  function writeSerialized(serialized: string[], bytes: number[], count: number): boolean {
    // JSON.stringify of { version, entries } is this header, the entries joined
    // by commas, and this footer; summing per-entry sizes avoids re-encoding
    // the whole partition on every eviction retry.
    let total = PARTITION_ENVELOPE_BYTES + Math.max(0, count - 1)
    for (let index = 0; index < count; index += 1) total += bytes[index]
    if (total > maxBytes) return false
    try {
      storage.setItem(
        storageKey,
        `${PARTITION_HEAD}${serialized.slice(0, count).join(',')}${PARTITION_TAIL}`,
      )
      return true
    } catch {
      return false
    }
  }

  function serializeEntries(entries: StoredEntry<Item, Cursor>[]): {
    serialized: string[]
    bytes: number[]
  } | null {
    try {
      const serialized = entries.map((entry) => JSON.stringify(entry))
      return { serialized, bytes: serialized.map(serializedBytes) }
    } catch {
      return null
    }
  }

  function write(partition: StoredPartition<Item, Cursor>): boolean {
    const encoded = serializeEntries(partition.entries)
    if (!encoded) return false
    return writeSerialized(encoded.serialized, encoded.bytes, partition.entries.length)
  }

  function restore(identityKey: string): BrowseSnapshotRestore<Item, Cursor> {
    const partition = read()
    const entry = partition.entries.find((candidate) => candidate.identityKey === identityKey)
    if (!entry) return { kind: 'missing', replayable: true }
    if (entry.snapshot === null) return { kind: 'expired', replayable: false }
    const expired = entry.metadata.expiresAt !== null && now() > entry.metadata.expiresAt
    if (expired) {
      if (!entry.metadata.replayable) {
        entry.snapshot = null
        entry.lastAccess = now()
        write(partition)
        return { kind: 'expired', replayable: false }
      }
      const remaining = partition.entries.filter(
        (candidate) => candidate.identityKey !== identityKey,
      )
      if (remaining.length === 0) clear()
      else write({ version: 1, entries: remaining })
      return { kind: 'expired', replayable: true }
    }
    // The touch only refreshes LRU order. If it cannot be persisted (the quota
    // is shared with every other source's partition) the stored partition is
    // still intact and the snapshot is still good, so return it regardless.
    entry.lastAccess = now()
    write(partition)
    return { kind: 'snapshot', snapshot: entry.snapshot, metadata: entry.metadata }
  }

  return {
    load(identityKey: string): BrowseSnapshot<Item, Cursor> | null {
      const restored = restore(identityKey)
      return restored.kind === 'snapshot' ? restored.snapshot : null
    },

    restore,

    save(
      identityKey: string,
      snapshot: BrowseSnapshot<Item, Cursor>,
      options: BrowseSnapshotSaveOptions = {},
    ): boolean {
      const limit = Math.max(0, maxEntries)
      if (limit === 0) {
        clear()
        return false
      }
      const partition = read()
      const savedAt = now()
      const ttlMs = options.ttlMs
      const expiresAt =
        ttlMs === undefined ? null : savedAt + Math.max(0, Number.isFinite(ttlMs) ? ttlMs : 0)
      const target: StoredEntry<Item, Cursor> = {
        identityKey,
        snapshot,
        lastAccess: savedAt,
        metadata: {
          replayable: options.replayable ?? true,
          savedAt,
          expiresAt,
        },
      }
      // The entry being saved is the most recent by definition, whatever the
      // clock says, so count eviction and fit eviction only ever pick among the
      // others, least recently used first.
      const others = partition.entries
        .filter((entry) => entry.identityKey !== identityKey)
        .sort(
          (left, right) =>
            right.lastAccess - left.lastAccess || left.identityKey.localeCompare(right.identityKey),
        )
        .slice(0, limit - 1)
      const encodedOthers = serializeEntries(others)
      if (!encodedOthers) {
        clear()
        return false
      }
      const encodedTarget = serializeEntries([target])
      if (encodedTarget) {
        const serialized = [...encodedTarget.serialized, ...encodedOthers.serialized]
        const bytes = [...encodedTarget.bytes, ...encodedOthers.bytes]
        // Shed the least recently used other entry one at a time until the
        // partition fits the byte budget and the storage quota.
        for (let count = serialized.length; count >= 1; count -= 1) {
          if (writeSerialized(serialized, bytes, count)) return true
        }
      }
      // The target cannot be stored even on its own. The partition may still
      // hold its previous snapshot, which would be restored as if it were
      // current — replace it with the other entries (as many as fit), or drop
      // the partition when nothing can be written at all.
      for (let count = others.length; count >= 1; count -= 1) {
        if (writeSerialized(encodedOthers.serialized, encodedOthers.bytes, count)) return false
      }
      clear()
      return false
    },

    remove(identityKey: string): void {
      const partition = read()
      const entries = partition.entries.filter((entry) => entry.identityKey !== identityKey)
      if (entries.length === partition.entries.length) return
      // A failed write would leave the removed entry in place to be restored
      // later, so fall back to dropping the partition.
      if (entries.length === 0 || !write({ version: 1, entries })) clear()
    },

    /**
     * Apply `patch` to every saved list of the partition. A changed list is
     * rewritten in place, its total lowered by the items removed; a list the
     * patch invalidates is discarded. Patching is not a visit, so LRU order is
     * kept. Reports whether anything changed.
     */
    patchItems(patch: BrowseListPatch<Item>): boolean {
      const partition = read()
      let changed = false
      const entries: StoredEntry<Item, Cursor>[] = []
      const rewritten = new Set<StoredEntry<Item, Cursor>>()
      for (const entry of partition.entries) {
        const snapshot = entry.snapshot
        if (snapshot === null) {
          entries.push(entry)
          continue
        }
        if (patch.invalidates?.(entry.identityKey, snapshot.pages.flat())) {
          changed = true
          continue
        }
        const patched = patchPages(snapshot.pages, (item) =>
          patch.updateItem(item, entry.identityKey),
        )
        if (!patched) {
          entries.push(entry)
          continue
        }
        changed = true
        const next: StoredEntry<Item, Cursor> = {
          ...entry,
          snapshot: {
            ...snapshot,
            pages: patched.pages,
            total: snapshot.total === null ? null : Math.max(0, snapshot.total - patched.removed),
          },
        }
        rewritten.add(next)
        entries.push(next)
      }
      if (!changed) return false
      if (entries.length === 0) {
        clear()
        return true
      }
      if (write({ version: 1, entries })) return true
      // The unpatched lists are still stored and would be restored as if they
      // were current: keep only the untouched ones, or drop the partition.
      const untouched = entries.filter((entry) => !rewritten.has(entry))
      if (untouched.length === 0 || !write({ version: 1, entries: untouched })) clear()
      return true
    },

    clear,
  }
}
