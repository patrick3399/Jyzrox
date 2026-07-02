import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { useEffect, useRef } from 'react'

const replace = vi.fn()
let searchStr = ''
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(searchStr),
}))
vi.mock('@/lib/api', () => ({
  api: {
    eh: {
      search: vi.fn(),
      getFavorites: vi.fn(),
      getPopular: vi.fn(),
      getToplist: vi.fn(),
    },
  },
}))

import { useEhBrowse } from '@/hooks/useEhBrowse'
import { api } from '@/lib/api'

beforeEach(() => {
  searchStr = ''
  replace.mockClear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

// Mimics VirtualGrid's trigger: a CHILD component whose passive effect fires
// onLoadMore as soon as items.length grows (the overshoot case where the last
// virtual row is already visible when the append commit renders). Child
// effects flush BEFORE the parent's effects, so this call happens before
// useEhBrowse's stateRef sync effect runs.
function GridStub({
  itemsLen,
  hasMore,
  loadMore,
}: {
  itemsLen: number
  hasMore: boolean
  loadMore: () => void
}) {
  const firedAt = useRef(-1)
  useEffect(() => {
    if (!hasMore) return
    if (firedAt.current >= itemsLen) return
    firedAt.current = itemsLen
    loadMore()
  }, [itemsLen, hasMore, loadMore])
  return null
}

type Hook = ReturnType<typeof useEhBrowse>
function Harness({ onState }: { onState: (h: Hook) => void }) {
  const hook = useEhBrowse()
  useEffect(() => {
    onState(hook)
  })
  return (
    <GridStub
      itemsLen={hook.state.items.length}
      hasMore={hook.state.hasMore}
      loadMore={hook.loadMore}
    />
  )
}

const g = (gid: number) => ({ gid, token: `t${gid}` })

describe('useEhBrowse — loadMore fired from a child effect in the append commit', () => {
  it('keeps loading when the grid re-fires onLoadMore in the same commit the append rendered', async () => {
    searchStr = 'tab=favorites'
    ;(api.eh.getFavorites as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        galleries: [g(1), g(2)],
        total: 6,
        has_next: true,
        next_cursor: 'A',
        categories: [],
      })
      .mockResolvedValueOnce({
        galleries: [g(3), g(4)],
        total: 6,
        has_next: true,
        next_cursor: 'B',
        categories: [],
      })
      .mockResolvedValueOnce({
        galleries: [g(5), g(6)],
        total: 6,
        has_next: false,
        next_cursor: null,
        categories: [],
      })

    let hook: Hook | null = null
    render(
      <Harness
        onState={(h) => {
          hook = h
        }}
      />,
    )

    // If the child-fired loadMore is swallowed by a stale status guard, the
    // list wedges at 2 items with hasMore=true and nothing ever re-fires.
    await waitFor(
      () => {
        expect(hook?.state.items.map((x) => x.gid)).toEqual([1, 2, 3, 4, 5, 6])
      },
      { timeout: 2000 },
    )
    expect(hook!.state.hasMore).toBe(false)
  })
})
