import { describe, expect, it } from 'vitest'
import { createBrowseReducer, createBrowseState } from '@/lib/browse/reducer'

type Item = { id: number; title: string }
type Cursor = string

const reducer = createBrowseReducer<Item, Cursor>((item) => item.id)

function hydrateA() {
  return reducer(createBrowseState<Item, Cursor>('A'), {
    type: 'HYDRATE',
    snapshot: {
      pages: [[{ id: 1, title: 'one' }], [{ id: 2, title: 'two' }]],
      cursor: 'cursor-2',
      hasMore: true,
      total: 9,
    },
  })
}

describe('browse reducer contracts', () => {
  it('hydrates pages, flattened items, cursor, hasMore, and total atomically', () => {
    const state = hydrateA()

    expect(state).toMatchObject({
      identityKey: 'A',
      pages: [[{ id: 1, title: 'one' }], [{ id: 2, title: 'two' }]],
      items: [
        { id: 1, title: 'one' },
        { id: 2, title: 'two' },
      ],
      cursor: 'cursor-2',
      hasMore: true,
      total: 9,
    })
  })

  it('rejects both stale success and stale error after an A to B to A round trip', () => {
    let state = reducer(createBrowseState<Item, Cursor>('A'), { type: 'REQUEST_STARTED' })
    const staleGeneration = state.generation

    state = reducer(state, { type: 'IDENTITY_CHANGED', identityKey: 'B' })
    state = reducer(state, { type: 'IDENTITY_CHANGED', identityKey: 'A' })
    const currentState = state

    state = reducer(state, {
      type: 'PAGE_SUCCEEDED',
      identityKey: 'A',
      generation: staleGeneration,
      mode: 'replace',
      page: {
        items: [{ id: 99, title: 'stale success' }],
        cursor: 'stale',
        hasMore: false,
        total: 1,
      },
    })
    expect(state).toEqual(currentState)

    state = reducer(state, {
      type: 'PAGE_FAILED',
      identityKey: 'A',
      generation: staleGeneration,
      error: new Error('stale error'),
    })
    expect(state).toEqual(currentState)
  })

  it('closes an all-duplicate append when its cursor does not advance', () => {
    let state = reducer(createBrowseState<Item, Cursor>('A'), {
      type: 'HYDRATE',
      snapshot: {
        pages: [[{ id: 1, title: 'one' }]],
        cursor: 'cursor-1',
        hasMore: true,
        total: 2,
      },
    })
    state = reducer(state, { type: 'REQUEST_STARTED' })

    state = reducer(state, {
      type: 'PAGE_SUCCEEDED',
      identityKey: 'A',
      generation: state.generation,
      mode: 'append',
      page: {
        items: [{ id: 1, title: 'duplicate' }],
        cursor: 'cursor-1',
        hasMore: true,
        total: 2,
      },
    })

    expect(state.items).toEqual([{ id: 1, title: 'one' }])
    expect(state.hasMore).toBe(false)
  })

  it('keeps loading possible when an all-duplicate append advances its cursor', () => {
    let state = reducer(createBrowseState<Item, Cursor>('A'), {
      type: 'HYDRATE',
      snapshot: {
        pages: [[{ id: 1, title: 'one' }]],
        cursor: 'cursor-1',
        hasMore: true,
        total: 2,
      },
    })
    state = reducer(state, { type: 'REQUEST_STARTED' })

    state = reducer(state, {
      type: 'PAGE_SUCCEEDED',
      identityKey: 'A',
      generation: state.generation,
      mode: 'append',
      page: {
        items: [{ id: 1, title: 'duplicate' }],
        cursor: 'cursor-2',
        hasMore: true,
        total: 2,
      },
    })

    expect(state.items).toEqual([{ id: 1, title: 'one' }])
    expect(state.cursor).toBe('cursor-2')
    expect(state.hasMore).toBe(true)
  })
})
