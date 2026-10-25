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

/**
 * Regression: every saved list of a source shares one storage key (its
 * partition). `write()` answered "this partition is over budget / the quota
 * threw" by clearing the WHOLE partition, so one oversized list wiped the up to
 * seven other lists a user could still back-navigate to ("upper page not
 * persisted"). `restore()` also reported `missing` when only its lastAccess
 * touch failed to persist, discarding a perfectly good snapshot.
 */
describe('browse snapshot store under storage pressure', () => {
  const textBytes = (value: string) => new TextEncoder().encode(value).byteLength

  /** A snapshot whose serialized size grows with `items`. */
  function sized(id: number, items: number): BrowseSnapshot<Item, Cursor> {
    return snapshot(id, {
      pages: [Array.from({ length: items }, (_, index) => ({ id: id * 10_000 + index }))],
    })
  }

  function partitionBytes(storage: Storage): number {
    return textBytes(storage.getItem(snapshotStorageKey(scope)) ?? '')
  }

  /** Bytes of a partition holding exactly these (identity, items) entries. */
  function bytesFor(entries: Array<[string, number]>): number {
    const storage = new MemoryStorage()
    let clock = 0
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      maxBytes: 10_000_000,
      now: () => ++clock,
    })
    entries.forEach(([key, items], index) => store.save(key, sized(index + 1, items)))
    return partitionBytes(storage)
  }

  it('evicts only the oldest other entry when a save pushes the partition over budget', () => {
    const storage = new MemoryStorage()
    let clock = 0
    const budget =
      bytesFor([
        ['A', 40],
        ['B', 40],
        ['C', 40],
      ]) + 20
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      maxBytes: budget,
      now: () => ++clock,
    })
    expect(store.save('A', sized(1, 40))).toBe(true)
    expect(store.save('B', sized(2, 40))).toBe(true)
    expect(store.save('C', sized(3, 40))).toBe(true)

    expect(store.save('D', sized(4, 40))).toBe(true)

    expect(store.load('D')).toEqual(sized(4, 40))
    expect(store.load('C')).toEqual(sized(3, 40))
    expect(store.load('B')).toEqual(sized(2, 40))
    expect(store.load('A')).toBeNull()
    expect(partitionBytes(storage)).toBeLessThanOrEqual(budget)
  })

  it('evicts further entries in least-recently-used order until a larger save fits', () => {
    const storage = new MemoryStorage()
    let clock = 0
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      maxBytes:
        bytesFor([
          ['A', 30],
          ['B', 30],
          ['C', 30],
        ]) + 20,
      now: () => ++clock,
    })
    store.save('A', sized(1, 30))
    store.save('B', sized(2, 30))
    store.save('C', sized(3, 30))

    // D is ~1.6x an entry: C + D fits, B + C + D does not, so A and B go.
    expect(store.save('D', sized(4, 60))).toBe(true)

    expect(store.load('D')).toEqual(sized(4, 60))
    expect(store.load('A')).toBeNull()
    expect(store.load('B')).toBeNull()
    expect(store.load('C')).toEqual(sized(3, 30))
  })

  it('keeps other identities when the target alone exceeds the budget, and drops its stale entry', () => {
    const storage = new MemoryStorage()
    let clock = 0
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      maxBytes:
        bytesFor([
          ['A', 30],
          ['B', 30],
          ['C', 30],
        ]) + 20,
      now: () => ++clock,
    })
    store.save('A', sized(1, 30))
    store.save('B', sized(2, 30))
    store.save('C', sized(3, 30))

    // B grew far past the whole budget: it can never be stored.
    expect(store.save('B', sized(2, 400))).toBe(false)

    // Its previous, now-stale snapshot must not be restored in place of it...
    expect(store.restore('B')).toEqual({ kind: 'missing', replayable: true })
    // ...but the other lists survive.
    expect(store.load('A')).toEqual(sized(1, 30))
    expect(store.load('C')).toEqual(sized(3, 30))
  })

  it('keeps other identities when the storage quota rejects the first write attempt', () => {
    // Quota in characters, like WebKit's UTF-16 accounting: the partition does
    // not fit while it still holds the oldest entry.
    class LimitedStorage extends MemoryStorage {
      limit = Number.POSITIVE_INFINITY
      override setItem(key: string, value: string): void {
        if (value.length > this.limit) throw new DOMException('quota', 'QuotaExceededError')
        super.setItem(key, value)
      }
    }
    const storage = new LimitedStorage()
    let clock = 0
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      maxBytes: 10_000_000,
      now: () => ++clock,
    })
    store.save('A', sized(1, 40))
    store.save('B', sized(2, 40))
    store.save('C', sized(3, 40))
    storage.limit = (storage.getItem(snapshotStorageKey(scope)) ?? '').length + 20

    expect(store.save('D', sized(4, 40))).toBe(true)

    expect(store.load('D')).toEqual(sized(4, 40))
    expect(store.load('C')).toEqual(sized(3, 40))
    expect(store.load('B')).toEqual(sized(2, 40))
    expect(store.load('A')).toBeNull()
  })

  it('keeps the other identities when the quota rejects the target even on its own', () => {
    class LimitedStorage extends MemoryStorage {
      limit = Number.POSITIVE_INFINITY
      override setItem(key: string, value: string): void {
        if (value.length > this.limit) throw new DOMException('quota', 'QuotaExceededError')
        super.setItem(key, value)
      }
    }
    const storage = new LimitedStorage()
    let clock = 0
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage,
      scope,
      maxBytes: 10_000_000,
      now: () => ++clock,
    })
    store.save('A', sized(1, 30))
    store.save('B', sized(2, 30))
    storage.limit = (storage.getItem(snapshotStorageKey(scope)) ?? '').length + 20

    expect(store.save('C', sized(3, 400))).toBe(false)

    expect(store.load('A')).toEqual(sized(1, 30))
    expect(store.load('B')).toEqual(sized(2, 30))
    expect(store.restore('C')).toEqual({ kind: 'missing', replayable: true })
  })

  it('returns the snapshot when only the lastAccess touch fails to persist', () => {
    class FlakyStorage extends MemoryStorage {
      failWrites = false
      override setItem(key: string, value: string): void {
        if (this.failWrites) throw new DOMException('quota', 'QuotaExceededError')
        super.setItem(key, value)
      }
    }
    const storage = new FlakyStorage()
    const store = createBrowseSnapshotStore<Item, Cursor>({ storage, scope })
    store.save('A', snapshot(1))
    store.save('B', snapshot(2))
    storage.failWrites = true

    expect(store.restore('A')).toMatchObject({ kind: 'snapshot', snapshot: snapshot(1) })

    // The failed touch must not have wiped the partition either.
    storage.failWrites = false
    expect(store.load('B')).toEqual(snapshot(2))
    expect(store.load('A')).toEqual(snapshot(1))
  })

  it('keeps the entry being saved when its timestamp ties with a full partition', () => {
    const store = createBrowseSnapshotStore<Item, Cursor>({
      storage: new MemoryStorage(),
      scope,
      maxEntries: 2,
      now: () => 7,
    })
    store.save('A', snapshot(1))
    store.save('B', snapshot(2))

    // 'C' sorts after both on the identity tie-break; it must still be stored.
    expect(store.save('C', snapshot(3))).toBe(true)
    expect(store.load('C')).toEqual(snapshot(3))
  })

  it('still clears a malformed partition instead of trusting any of it', () => {
    const storage = new MemoryStorage()
    storage.setItem(
      snapshotStorageKey(scope),
      JSON.stringify({ version: 1, entries: [{ identityKey: 'A', snapshot: 'not-a-snapshot' }] }),
    )
    const store = createBrowseSnapshotStore<Item, Cursor>({ storage, scope })

    expect(store.save('B', snapshot(2))).toBe(true)

    expect(store.load('A')).toBeNull()
    expect(store.load('B')).toEqual(snapshot(2))
  })
})
