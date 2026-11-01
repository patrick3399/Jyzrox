/**
 * useGalleryEventRefresh — refreshes the open gallery on its own WS events.
 *
 * useSWRInfinite keys are skipped by SWR's global mutate(filter), and the
 * reader page is not SWR-backed at all, so both subscribe to gallery.* /
 * import.* events through this hook instead.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { WsMessage } from '@/lib/types'

const { state } = vi.hoisted(() => ({ state: { lastEvent: null as WsMessage | null } }))

vi.mock('@/lib/ws', () => ({
  useWsEvents: () => ({ lastEvent: state.lastEvent }),
}))
vi.mock('swr', () => ({ mutate: vi.fn() }))

import { useGalleryEventRefresh } from '@/hooks/useGalleryEventRefresh'

function event(
  event_type: string,
  resource_id: string | number | null,
  resource_type = 'gallery',
): WsMessage {
  return {
    type: 'event',
    event: { event_type, resource_type, resource_id, data: {} },
  } as WsMessage
}

describe('useGalleryEventRefresh', () => {
  beforeEach(() => {
    state.lastEvent = null
  })

  it('calls onRefresh for a gallery.updated event for this gallery', () => {
    const onRefresh = vi.fn()
    const { rerender } = renderHook(() => useGalleryEventRefresh(7, onRefresh))
    expect(onRefresh).not.toHaveBeenCalled()

    state.lastEvent = event('gallery.updated', 7)
    rerender()

    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('matches a string resource_id against the numeric gallery id', () => {
    const onRefresh = vi.fn()
    const { rerender } = renderHook(() => useGalleryEventRefresh(7, onRefresh))

    state.lastEvent = event('gallery.updated', '7')
    rerender()

    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('also reacts to import.* events for this gallery', () => {
    const onRefresh = vi.fn()
    const { rerender } = renderHook(() => useGalleryEventRefresh(7, onRefresh))

    state.lastEvent = event('import.completed', 7)
    rerender()

    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('ignores an event for another gallery', () => {
    const onRefresh = vi.fn()
    const { rerender } = renderHook(() => useGalleryEventRefresh(7, onRefresh))

    state.lastEvent = event('gallery.updated', 8)
    rerender()

    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('ignores events of unrelated types even when the id matches', () => {
    const onRefresh = vi.fn()
    const { rerender } = renderHook(() => useGalleryEventRefresh(7, onRefresh))

    state.lastEvent = event('subscription.updated', 7)
    rerender()

    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('does nothing while the gallery id is unknown', () => {
    const onRefresh = vi.fn()
    const { rerender } = renderHook(() => useGalleryEventRefresh(undefined, onRefresh))

    state.lastEvent = event('gallery.updated', 7)
    rerender()

    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('does not replay an old event when the gallery id becomes known later', () => {
    const onRefresh = vi.fn()
    state.lastEvent = event('gallery.updated', 7)
    const { rerender } = renderHook(
      ({ id }: { id: number | undefined }) => useGalleryEventRefresh(id, onRefresh),
      { initialProps: { id: undefined as number | undefined } },
    )

    rerender({ id: 7 })

    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('does not refire when only the callback identity changes', () => {
    const first = vi.fn()
    const second = vi.fn()
    state.lastEvent = null
    const { rerender } = renderHook(
      ({ cb }: { cb: () => void }) => useGalleryEventRefresh(7, cb),
      { initialProps: { cb: first as () => void } },
    )
    state.lastEvent = event('gallery.updated', 7)
    rerender({ cb: first })
    expect(first).toHaveBeenCalledTimes(1)

    rerender({ cb: second })

    expect(first).toHaveBeenCalledTimes(1)
    expect(second).not.toHaveBeenCalled()
  })

  it('invokes the latest callback, not the one captured when the event arrived', () => {
    const stale = vi.fn()
    const fresh = vi.fn()
    const { rerender } = renderHook(
      ({ cb }: { cb: () => void }) => useGalleryEventRefresh(7, cb),
      { initialProps: { cb: stale as () => void } },
    )

    state.lastEvent = event('gallery.updated', 7)
    rerender({ cb: fresh })

    expect(stale).not.toHaveBeenCalled()
    expect(fresh).toHaveBeenCalledTimes(1)
  })
})
