import type { BrowseAnchor } from './anchor'

export type BrowseLayoutSnapshot = {
  columns: number
  width: number
  mode: string
}

export type BrowseSnapshot<Item, Cursor> = {
  pages: Item[][]
  cursor: Cursor | null
  hasMore: boolean
  total: number | null
  anchor: BrowseAnchor | null
  layout: BrowseLayoutSnapshot | null
  pageMeta?: unknown
}

export type BrowseSnapshotScope = {
  userId: string
  tabId: string
  sourceId: string
  schemaVersion: number
}

export type StoredEntry<Item, Cursor> = {
  identityKey: string
  snapshot: BrowseSnapshot<Item, Cursor> | null
  lastAccess: number
  metadata: BrowseSnapshotMetadata
}

export type StoredPartition<Item, Cursor> = {
  version: 1
  entries: StoredEntry<Item, Cursor>[]
}

export type StoreOptions = {
  storage: Storage
  scope: BrowseSnapshotScope
  maxEntries?: number
  maxBytes?: number
  now?: () => number
  validateCursor?: (value: unknown) => boolean
  validateItem?: (value: unknown) => boolean
  validateMeta?: (value: unknown) => boolean
}

export type BrowseSnapshotMetadata = {
  replayable: boolean
  savedAt: number
  expiresAt: number | null
}

export type BrowseSnapshotSaveOptions = {
  replayable?: boolean
  ttlMs?: number
}

export type BrowseSnapshotRestore<Item, Cursor> =
  | {
      kind: 'snapshot'
      snapshot: BrowseSnapshot<Item, Cursor>
      metadata: BrowseSnapshotMetadata
    }
  | { kind: 'expired'; replayable: boolean }
  | { kind: 'missing'; replayable: true }
