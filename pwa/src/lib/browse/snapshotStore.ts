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

type StoredEntry<Item, Cursor> = {
  identityKey: string
  snapshot: BrowseSnapshot<Item, Cursor> | null
  lastAccess: number
  metadata: BrowseSnapshotMetadata
}

type StoredPartition<Item, Cursor> = {
  version: 1
  entries: StoredEntry<Item, Cursor>[]
}

type StoreOptions = {
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

const DEFAULT_MAX_ENTRIES = 8
const DEFAULT_MAX_BYTES = 2_000_000

// Superseded by the scoped partitions below. Safe to delete outright once the
// compatibility migrations that read them are retired.
const RETIRED_BROWSE_KEYS = [
  'eh_browse_snapshot',
  'library_scrollY',
  'pixiv_ranking_scrollY',
  'pixiv_feed_scrollY',
  'pixiv_bookmarks_scrollY',
  'pixiv_search_scrollY',
] as const

// Current-generation keys owned by the live navigation and tab-scope modules.
// They are cleared on logout — not because they are obsolete, but because the
// next session in this tab must not inherit the previous user's browsing
// position or tab identity. Do not fold these into the retired list.
const ACTIVE_PER_USER_BROWSE_KEYS = [
  'nav_memory_v1',
  'nav_restore_flag_v1',
  'browse_session_tab_id_v1',
] as const

const KEYS_CLEARED_ON_LOGOUT = new Set<string>([
  ...RETIRED_BROWSE_KEYS,
  ...ACTIVE_PER_USER_BROWSE_KEYS,
])

export function clearBrowseSessionStorage(storage: Storage): void {
  const remove: string[] = []
  let length: number
  try {
    length = storage.length
  } catch {
    return
  }
  for (let index = 0; index < length; index += 1) {
    let key: string | null
    try {
      key = storage.key(index)
    } catch {
      continue
    }
    if (key && (KEYS_CLEARED_ON_LOGOUT.has(key) || key.startsWith('browse_session_v1:'))) {
      remove.push(key)
    }
  }
  for (const key of remove) {
    try {
      storage.removeItem(key)
    } catch {
      // Logout cleanup is best effort; one inaccessible key must not prevent
      // the remaining scoped and legacy partitions from being invalidated.
    }
  }
}

export function snapshotStorageKey(scope: BrowseSnapshotScope): string {
  return [
    'browse_session_v1',
    encodeURIComponent(scope.userId),
    encodeURIComponent(scope.tabId),
    encodeURIComponent(scope.sourceId),
    String(scope.schemaVersion),
  ].join(':')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isFiniteNonNegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

function isMetadata(value: unknown): value is BrowseSnapshotMetadata {
  if (!isRecord(value)) return false
  if (typeof value.replayable !== 'boolean' || !isFiniteNonNegative(value.savedAt)) return false
  return (
    value.expiresAt === null ||
    (isFiniteNonNegative(value.expiresAt) && value.expiresAt >= value.savedAt)
  )
}

function isAnchor(value: unknown): boolean {
  if (!isRecord(value)) return false
  const itemId = value.itemId
  return (
    (itemId === null || typeof itemId === 'string' || typeof itemId === 'number') &&
    typeof value.offset === 'number' &&
    Number.isFinite(value.offset) &&
    isFiniteNonNegative(value.scrollY)
  )
}

function isLayout(value: unknown): boolean {
  if (!isRecord(value)) return false
  return (
    typeof value.columns === 'number' &&
    Number.isInteger(value.columns) &&
    value.columns > 0 &&
    isFiniteNonNegative(value.width) &&
    typeof value.mode === 'string' &&
    value.mode.length > 0
  )
}

function isSnapshot(
  value: unknown,
  validateCursor?: (value: unknown) => boolean,
  validateItem?: (value: unknown) => boolean,
  validateMeta?: (value: unknown) => boolean,
): boolean {
  if (!isRecord(value)) return false
  return (
    Array.isArray(value.pages) &&
    value.pages.every(
      (page) => Array.isArray(page) && (!validateItem || page.every(validateItem)),
    ) &&
    'cursor' in value &&
    (value.cursor === null || !validateCursor || validateCursor(value.cursor)) &&
    typeof value.hasMore === 'boolean' &&
    (value.total === null || isFiniteNonNegative(value.total)) &&
    (value.anchor === null || isAnchor(value.anchor)) &&
    (value.layout === null || isLayout(value.layout)) &&
    (!validateMeta || validateMeta(value.pageMeta))
  )
}

function parsePartition<Item, Cursor>(
  raw: string,
  validateCursor?: (value: unknown) => boolean,
  validateItem?: (value: unknown) => boolean,
  validateMeta?: (value: unknown) => boolean,
): StoredPartition<Item, Cursor> | null {
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed) || parsed.version !== 1 || !Array.isArray(parsed.entries)) return null
    const entries: StoredEntry<Item, Cursor>[] = []
    for (const value of parsed.entries) {
      if (
        !isRecord(value) ||
        typeof value.identityKey !== 'string' ||
        typeof value.lastAccess !== 'number' ||
        !Number.isFinite(value.lastAccess) ||
        !isMetadata(value.metadata) ||
        (value.snapshot === null
          ? value.metadata.replayable
          : !isSnapshot(value.snapshot, validateCursor, validateItem, validateMeta))
      ) {
        return null
      }
      entries.push(value as StoredEntry<Item, Cursor>)
    }
    return { version: 1, entries }
  } catch {
    return null
  }
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

  function write(partition: StoredPartition<Item, Cursor>): boolean {
    let raw: string
    try {
      raw = JSON.stringify(partition)
    } catch {
      clear()
      return false
    }
    if (serializedBytes(raw) > maxBytes) {
      clear()
      return false
    }
    try {
      storage.setItem(storageKey, raw)
      return true
    } catch {
      clear()
      return false
    }
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
    entry.lastAccess = now()
    if (!write(partition)) return { kind: 'missing', replayable: true }
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
      const partition = read()
      const entries = partition.entries.filter((entry) => entry.identityKey !== identityKey)
      const savedAt = now()
      const ttlMs = options.ttlMs
      const expiresAt =
        ttlMs === undefined ? null : savedAt + Math.max(0, Number.isFinite(ttlMs) ? ttlMs : 0)
      entries.push({
        identityKey,
        snapshot,
        lastAccess: savedAt,
        metadata: {
          replayable: options.replayable ?? true,
          savedAt,
          expiresAt,
        },
      })
      entries.sort(
        (left, right) =>
          right.lastAccess - left.lastAccess || left.identityKey.localeCompare(right.identityKey),
      )
      const bounded = {
        version: 1 as const,
        entries: entries.slice(0, Math.max(0, maxEntries)),
      }
      if (!bounded.entries.some((entry) => entry.identityKey === identityKey)) {
        clear()
        return false
      }
      return write(bounded)
    },

    remove(identityKey: string): void {
      const partition = read()
      const entries = partition.entries.filter((entry) => entry.identityKey !== identityKey)
      if (entries.length === partition.entries.length) return
      if (entries.length === 0) clear()
      else write({ version: 1, entries })
    },

    clear,
  }
}
