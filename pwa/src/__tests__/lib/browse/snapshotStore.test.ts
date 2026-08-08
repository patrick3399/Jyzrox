import { describe, expect, it } from 'vitest'
import {
  createBrowseSnapshotStore,
  snapshotStorageKey,
  type BrowseSnapshot,
  type BrowseSnapshotScope,
} from '@/lib/browse/snapshotStore'

type Item = { id: number }
type Cursor = string

class MemoryStorage implements Storage {
  protected values = new Map<string, string>()

  get length() {
    return this.values.size
  }

  clear() {
    this.values.clear()
  }

  getItem(key: string) {
    return this.values.get(key) ?? null
  }

  key(index: number) {
    return [...this.values.keys()][index] ?? null
  }

  removeItem(key: string) {
    this.values.delete(key)
  }

  setItem(key: string, value: string) {
    this.values.set(key, value)
  }
}

const scope: BrowseSnapshotScope = {
  userId: '42',
  tabId: 'tab-a',
  sourceId: 'library',
  schemaVersion: 1,
}

function snapshot(id: number, overrides: Partial<BrowseSnapshot<Item, Cursor>> = {}) {
  return {
    pages: [[{ id }]],
    cursor: `cursor-${id}`,
    hasMore: true,
    total: 10,
    anchor: { itemId: id, offset: 8, scrollY: 400 },
    layout: { columns: 4, width: 1200, mode: 'grid' },
    ...overrides,
  } satisfies BrowseSnapshot<Item, Cursor>
}

function storedPartition(identityKey: string, value: unknown, metadata?: unknown): string {
  return JSON.stringify({
    version: 1,
    entries: [
      {
        identityKey,
        snapshot: value,
        lastAccess: 1,
        metadata: metadata ?? { replayable: true, savedAt: 1, expiresAt: null },
      },
    ],
  })
}

describe('browse snapshot store contracts', () => {
  it('partitions deterministically by user, browser tab, source, and schema', () => {
    expect(snapshotStorageKey(scope)).toBe(snapshotStorageKey({ ...scope }))
    expect(snapshotStorageKey(scope)).not.toBe(snapshotStorageKey({ ...scope, userId: '43' }))
    expect(snapshotStorageKey(scope)).not.toBe(snapshotStorageKey({ ...scope, tabId: 'tab-b' }))
    expect(snapshotStorageKey(scope)).not.toBe(snapshotStorageKey({ ...scope, sourceId: 'pixiv' }))
    expect(snapshotStorageKey(scope)).not.toBe(snapshotStorageKey({ ...scope, schemaVersion: 2 }))
  })

  it('uses deterministic least-recently-used eviction and touches successful reads', () => {
    const storage = new MemoryStorage()
    let clock = 0
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      maxEntries: 2,
      maxBytes: 100_000,
      now: () => ++clock,
    })

    expect(store.save('A', snapshot(1))).toBe(true)
    expect(store.save('B', snapshot(2))).toBe(true)
    expect(store.load('A')).toEqual(snapshot(1))
    expect(store.save('C', snapshot(3))).toBe(true)

    expect(store.load('A')).toEqual(snapshot(1))
    expect(store.load('B')).toBeNull()
    expect(store.load('C')).toEqual(snapshot(3))
  })

  it('fails closed and clears its partition when persisted JSON is malformed', () => {
    const storage = new MemoryStorage()
    storage.setItem(snapshotStorageKey(scope), '{malformed')
    const store = createBrowseSnapshotStore<Item, Cursor>({ storage, scope })

    expect(store.load('A')).toBeNull()
    expect(storage.getItem(snapshotStorageKey(scope))).toBeNull()
  })

  it('fails closed without throwing when a write exceeds quota or the storage write throws', () => {
    const smallStorage = new MemoryStorage()
    const smallStore = createBrowseSnapshotStore<Item, Cursor>({
      storage: smallStorage,
      scope,
      maxBytes: 32,
    })
    expect(smallStore.save('A', snapshot(1))).toBe(false)
    expect(smallStore.load('A')).toBeNull()

    class QuotaStorage extends MemoryStorage {
      override setItem(): void {
        throw new DOMException('quota', 'QuotaExceededError')
      }
    }
    const quotaStore = createBrowseSnapshotStore<Item, Cursor>({
      storage: new QuotaStorage(),
      scope,
    })
    expect(() => quotaStore.save('A', snapshot(1))).not.toThrow()
    expect(quotaStore.save('A', snapshot(1))).toBe(false)
    expect(quotaStore.load('A')).toBeNull()
  })

  it('round-trips an empty terminal snapshot instead of reviving older items', () => {
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage: new MemoryStorage(),
      scope,
    })
    const empty = snapshot(1, {
      pages: [[]],
      cursor: null,
      hasMore: false,
      total: 0,
      anchor: null,
    })

    expect(store.save('empty-search', empty)).toBe(true)
    expect(store.load('empty-search')).toEqual(empty)
  })

  it.each([
    ['cursor', { ...snapshot(1), cursor: 42 }],
    ['anchor offset', { ...snapshot(1), anchor: { itemId: 1, offset: '8', scrollY: 400 } }],
    ['anchor scrollY', { ...snapshot(1), anchor: { itemId: 1, offset: 8, scrollY: -1 } }],
    ['layout columns', { ...snapshot(1), layout: { columns: 0, width: 1200, mode: 'grid' } }],
    ['layout width', { ...snapshot(1), layout: { columns: 4, width: 'wide', mode: 'grid' } }],
    ['total', { ...snapshot(1), total: -1 }],
  ])('rejects invalid persisted %s data and clears the partition', (_name, invalid) => {
    const storage = new MemoryStorage()
    storage.setItem(snapshotStorageKey(scope), storedPartition('bad', invalid))
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      validateCursor: (value): value is Cursor => typeof value === 'string',
    })

    expect(store.load('bad')).toBeNull()
    expect(storage.getItem(snapshotStorageKey(scope))).toBeNull()
  })

  it.each([
    ['page item', { ...snapshot(1), pages: [[{ id: 'not-an-integer' }]] }],
    [
      'page metadata',
      { ...snapshot(1), pageMeta: { favoriteCategories: [{ id: 'not-an-integer' }] } },
    ],
  ])('rejects an invalid persisted %s through adapter validators', (_name, invalid) => {
    const storage = new MemoryStorage()
    storage.setItem(snapshotStorageKey(scope), storedPartition('bad-adapter-data', invalid))
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      validateCursor: (value): value is Cursor => typeof value === 'string',
      validateItem: (value): value is Item => {
        if (value === null || typeof value !== 'object') return false
        return Number.isInteger((value as { id?: unknown }).id)
      },
      validateMeta: (value) => {
        if (value === undefined) return true
        if (value === null || typeof value !== 'object') return false
        const categories = (value as { favoriteCategories?: unknown }).favoriteCategories
        return (
          Array.isArray(categories) &&
          categories.every(
            (category) =>
              category !== null &&
              typeof category === 'object' &&
              Number.isInteger((category as { id?: unknown }).id),
          )
        )
      },
    })

    expect(store.load('bad-adapter-data')).toBeNull()
    expect(storage.getItem(snapshotStorageKey(scope))).toBeNull()
  })

  it('accepts every page item and page metadata when adapter validators approve them', () => {
    const storage = new MemoryStorage()
    const valid = {
      ...snapshot(1),
      pages: [[{ id: 1 }], [{ id: 2 }]],
      pageMeta: { favoriteCategories: [{ id: 3 }] },
    }
    storage.setItem(snapshotStorageKey(scope), storedPartition('valid-adapter-data', valid))
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      validateCursor: (value): value is Cursor => typeof value === 'string',
      validateItem: (value): value is Item =>
        value !== null &&
        typeof value === 'object' &&
        Number.isInteger((value as { id?: unknown }).id),
      validateMeta: (value) =>
        value !== null &&
        typeof value === 'object' &&
        Array.isArray((value as { favoriteCategories?: unknown }).favoriteCategories),
    })

    expect(store.load('valid-adapter-data')).toEqual(valid)
  })

  it('expires replayable snapshots by TTL and reports that the identity may be fetched again', () => {
    const storage = new MemoryStorage()
    let clock = 100
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      now: () => clock,
    })
    expect(store.save('A', snapshot(1), { replayable: true, ttlMs: 50 })).toBe(true)
    expect(store.restore('A')).toMatchObject({
      kind: 'snapshot',
      snapshot: snapshot(1),
      metadata: { replayable: true, savedAt: 100, expiresAt: 150 },
    })

    clock = 151
    expect(store.restore('A')).toEqual({ kind: 'expired', replayable: true })
    expect(store.restore('A')).toEqual({ kind: 'missing', replayable: true })
  })

  it('retains a terminal tombstone when a non-replayable snapshot expires', () => {
    const storage = new MemoryStorage()
    let clock = 200
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      now: () => clock,
    })
    expect(store.save('upload', snapshot(1), { replayable: false, ttlMs: 25 })).toBe(true)

    clock = 226
    expect(store.restore('upload')).toEqual({ kind: 'expired', replayable: false })
    expect(store.restore('upload')).toEqual({ kind: 'expired', replayable: false })
    expect(store.load('upload')).toBeNull()
  })
})
