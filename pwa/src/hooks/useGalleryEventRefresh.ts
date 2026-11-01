'use client'

import { useEffect, useLayoutEffect, useRef } from 'react'
import { useWsEvents } from '@/lib/ws'
import { extractEventPayload } from '@/lib/wsInvalidation'
import type { WsMessage } from '@/lib/types'

const useIsomorphicLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

/** True for a gallery.* / import.* event whose resource is the given gallery. */
export function isGalleryEvent(msg: WsMessage | null, galleryId: number): boolean {
  const payload = extractEventPayload(msg)
  if (!payload) return false
  if (!payload.event_type.startsWith('gallery.') && !payload.event_type.startsWith('import.')) {
    return false
  }
  return payload.resource_id != null && String(payload.resource_id) === String(galleryId)
}

/**
 * Calls `onRefresh` when a gallery.* / import.* WebSocket event arrives for
 * `galleryId`.
 *
 * WsInvalidationBridge refreshes SWR keys with `mutate(filter)`, but SWR skips
 * `useSWRInfinite` keys there, and the reader page keeps its data in
 * `useState`. Both therefore subscribe here instead.
 *
 * `onRefresh` lives in a ref updated in a layout effect (FE-T11 / FE-T19) so a
 * new callback identity neither re-subscribes nor replays the last event. The
 * last handled event is remembered so that learning the gallery id late does
 * not replay an event that was already on the context.
 */
export function useGalleryEventRefresh(
  galleryId: number | null | undefined,
  onRefresh: () => void,
) {
  const { lastEvent } = useWsEvents()
  const onRefreshRef = useRef(onRefresh)
  const handledEventRef = useRef<WsMessage | null>(lastEvent)

  useIsomorphicLayoutEffect(() => {
    onRefreshRef.current = onRefresh
  })

  useEffect(() => {
    if (lastEvent === handledEventRef.current) return
    handledEventRef.current = lastEvent
    if (galleryId == null) return
    if (!isGalleryEvent(lastEvent, galleryId)) return
    onRefreshRef.current()
  }, [lastEvent, galleryId])
}
