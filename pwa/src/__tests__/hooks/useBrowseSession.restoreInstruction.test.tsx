import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useBrowseSession } from '@/lib/browse/useBrowseSession'
import { createBrowseSnapshotStore, type BrowseSnapshotScope } from '@/lib/browse/snapshotStore'

type Item = { id: number }
type Identity = { query: string }
type Cursor = string
type View = {
  anchor: { itemId: number | null; offset: number; scrollY: number } | null
  layout: { columns: number; width: number; mode: string } | null
}
type RestoreInstruction = {
  key: string
  identityKey: string
  target: { kind: 'view'; view: View } | { kind: 'top' }
}
type DesiredBrowseSessionContract = {
  restoreInstruction: RestoreInstruction | null
  acknowledgeRestore: (key: string) => void
  updateView: (view: View) => void
  checkpoint: (view: View) => boolean
}

class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() { return this.values.size }
  clear() { this.values.clear() }
  getItem(key: string) { return this.values.get(key) ?? null }
  key(index: number) { return [...this.values.keys()][index] ?? null }
  removeItem(key: string) { this.values.delete(key) }
  setItem(key: string, value: string) { this.values.set(key, value) }
}

const scope: BrowseSnapshotScope = {
  userId: 'member-1',
  tabId: 'tab-1',
  sourceId: 'test',
  schemaVersion: 1,
}

function desiredContract(result: unknown): DesiredBrowseSessionContract {
  return result as DesiredBrowseSessionContract
}

function snapshotView(itemId: number, scrollY: number): View {
  return {
    anchor: { itemId, offset: 12, scrollY },
    layout: { columns: 4, width: 1200, mode: 'grid' },
  }
}

describe('useBrowseSession one-shot restore instruction contract', () => {
  it('does not turn a live update or checkpoint into another restore instruction', async () => {
    const storage = new MemoryStorage()
    const initialView = snapshotView(1, 400)
    createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save('search:A', {
      pages: [[{ id: 1 }]],
      cursor: null,
      hasMore: false,
      total: 1,
      ...initialView,
    })
    const view = renderHook(() =>
      useBrowseSession<Item, Cursor, Identity>({
        identity: { query: 'A' },
        identityKey: 'search:A',
        adapter: {
          getItemId: (item) => item.id,
          fetchPage: vi.fn(),
        },
        scope,
        storage,
        autoLoad: false,
      }),
    )

    await waitFor(() =>
      expect(desiredContract(view.result.current).restoreInstruction?.target.kind).toBe('view'),
    )
    const original = desiredContract(view.result.current).restoreInstruction
    const liveView = snapshotView(1, 900)

    act(() => desiredContract(view.result.current).updateView(liveView))
    expect(desiredContract(view.result.current).restoreInstruction).toEqual(original)

    act(() => desiredContract(view.result.current).checkpoint(liveView))
    expect(desiredContract(view.result.current).restoreInstruction).toEqual(original)
  })

  it('replaces A with an identity-tagged top instruction for missing B when auto-load is disabled', async () => {
    const storage = new MemoryStorage()
    const aView = snapshotView(1, 700)
    createBrowseSnapshotStore<Item, Cursor>({ storage, scope }).save('search:A', {
      pages: [[{ id: 1 }]],
      cursor: null,
      hasMore: false,
      total: 1,
      ...aView,
    })
    const view = renderHook(
      ({ query }) =>
        useBrowseSession<Item, Cursor, Identity>({
          identity: { query },
          identityKey: `search:${query}`,
          adapter: { getItemId: (item) => item.id, fetchPage: vi.fn() },
          scope,
          storage,
          autoLoad: false,
        }),
      { initialProps: { query: 'A' } },
    )
    await waitFor(() =>
      expect(desiredContract(view.result.current).restoreInstruction?.identityKey).toBe('search:A'),
    )

    view.rerender({ query: 'B' })

    await waitFor(() => {
      expect(desiredContract(view.result.current).restoreInstruction).toMatchObject({
        identityKey: 'search:B',
        target: { kind: 'top' },
      })
    })
  })

  it('acknowledges only the matching instruction key', async () => {
    const storage = new MemoryStorage()
    const view = renderHook(() =>
      useBrowseSession<Item, Cursor, Identity>({
        identity: { query: 'missing' },
        identityKey: 'search:missing',
        adapter: { getItemId: (item) => item.id, fetchPage: vi.fn() },
        scope,
        storage,
        autoLoad: false,
      }),
    )
    await waitFor(() =>
      expect(desiredContract(view.result.current).restoreInstruction?.target.kind).toBe('top'),
    )
    const instruction = desiredContract(view.result.current).restoreInstruction!

    act(() => desiredContract(view.result.current).acknowledgeRestore(`${instruction.key}:stale`))
    expect(desiredContract(view.result.current).restoreInstruction).toEqual(instruction)

    act(() => desiredContract(view.result.current).acknowledgeRestore(instruction.key))
    expect(desiredContract(view.result.current).restoreInstruction).toBeNull()
  })
})
