import type { BrowseSnapshotMetadata, StoredEntry, StoredPartition } from './snapshotTypes'

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

export function parsePartition<Item, Cursor>(
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
