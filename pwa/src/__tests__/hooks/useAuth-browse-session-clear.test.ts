import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { clearSWUserCaches, logout, mutate, push, refresh } = vi.hoisted(() => ({
  clearSWUserCaches: vi.fn(),
  logout: vi.fn(),
  mutate: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, refresh }),
}))

vi.mock('swr', () => ({
  default: vi.fn(),
  mutate,
}))

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))
vi.mock('@/lib/api', () => ({ api: { auth: { logout } } }))
vi.mock('@/lib/swCacheConfig', () => ({ clearSWUserCaches }))

import { useAuth } from '@/hooks/useAuth'
import { createBrowseSnapshotStore, type BrowseSnapshot } from '@/lib/browse/snapshotStore'

beforeEach(() => {
  sessionStorage.clear()
  vi.clearAllMocks()
  logout.mockResolvedValue({ status: 'ok' })
  mutate.mockResolvedValue(undefined)
})

describe('logout browse-session cleanup', () => {
  it('clears legacy and browse_session_v1 partitions without clearing unrelated sessionStorage', async () => {
    sessionStorage.setItem('eh_browse_snapshot', '{"version":2,"snaps":[]}')
    sessionStorage.setItem('nav_memory_v1', '{}')
    sessionStorage.setItem('nav_restore_flag_v1', '/e-hentai/1/token')
    sessionStorage.setItem('browse_session_v1:42:tab-a:ehentai:1', '{}')
    sessionStorage.setItem('browse_session_v1:42:tab-a:library:1', '{}')
    sessionStorage.setItem('unrelated_feature_state', 'keep-me')

    const { result } = renderHook(() => useAuth())
    await act(async () => result.current.logout())

    expect(sessionStorage.getItem('eh_browse_snapshot')).toBeNull()
    expect(sessionStorage.getItem('nav_memory_v1')).toBeNull()
    expect(sessionStorage.getItem('nav_restore_flag_v1')).toBeNull()
    expect(sessionStorage.getItem('browse_session_v1:42:tab-a:ehentai:1')).toBeNull()
    expect(sessionStorage.getItem('browse_session_v1:42:tab-a:library:1')).toBeNull()
    expect(sessionStorage.getItem('unrelated_feature_state')).toBe('keep-me')
  })

  it('does not allow a user A snapshot partition to hydrate user B', () => {
    type Item = { gid: number }
    type Cursor = string
    const snapshot: BrowseSnapshot<Item, Cursor> = {
      pages: [[{ gid: 1 }]],
      cursor: 'next',
      hasMore: true,
      total: 2,
      anchor: null,
      layout: null,
    }
    const common = { tabId: 'tab-a', sourceId: 'ehentai', schemaVersion: 1 }
    const userA = createBrowseSnapshotStore<Item, Cursor>({
      storage: sessionStorage,
      scope: { ...common, userId: 'A' },
    })
    const userB = createBrowseSnapshotStore<Item, Cursor>({
      storage: sessionStorage,
      scope: { ...common, userId: 'B' },
    })

    expect(userA.save('favorites', snapshot)).toBe(true)
    expect(userB.load('favorites')).toBeNull()
    expect(userA.load('favorites')).toEqual(snapshot)
  })

  it.each(['length', 'key', 'removeItem'] as const)(
    'continues logout when sessionStorage.%s throws',
    async (failure) => {
      const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
      const throwingStorage = {
        get length() {
          if (failure === 'length') throw new DOMException('blocked', 'SecurityError')
          return 1
        },
        clear: vi.fn(),
        getItem: vi.fn(() => null),
        key: vi.fn(() => {
          if (failure === 'key') throw new DOMException('blocked', 'SecurityError')
          return 'browse_session_v1:42:tab-a:ehentai:1'
        }),
        removeItem: vi.fn(() => {
          if (failure === 'removeItem') throw new DOMException('blocked', 'SecurityError')
        }),
        setItem: vi.fn(),
      } satisfies Storage
      Object.defineProperty(globalThis, 'sessionStorage', {
        value: throwingStorage,
        configurable: true,
      })

      try {
        const { result } = renderHook(() => useAuth())
        await act(async () => result.current.logout())

        expect(clearSWUserCaches).toHaveBeenCalledOnce()
        expect(push).toHaveBeenCalledWith('/login')
        expect(refresh).toHaveBeenCalledOnce()
      } finally {
        if (original) Object.defineProperty(globalThis, 'sessionStorage', original)
      }
    },
  )
})
