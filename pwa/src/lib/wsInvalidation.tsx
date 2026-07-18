'use client'

/**
 * wsInvalidation.tsx — BR-005/F5 event-driven SWR cache invalidation.
 *
 * A flat registry (same style as `pageRegistry.ts`) maps EventBus
 * `event_type` values to SWR cache-key invalidation rules. `<WsInvalidationBridge />`
 * mounts once inside `WsProvider` (see `components/LayoutShell.tsx`), watches
 * `useWsEvents().lastEvent`, and calls SWR's global `mutate(filterFn)` for
 * whichever rule matches. Event types with no matching rule are ignored —
 * there is deliberately no catch-all `mutate()` call.
 *
 * Coverage note — `download.*` is NOT reachable via `lastEvent` today:
 * the backend WS relay (`routers/ws.py::_event_to_ws_message`) translates
 * every `download.*` event (resource_type `download_job`) into the legacy
 * `{"type": "job_update", ...}` message shape before it reaches the client.
 * `ws.tsx` branches `job_update` messages into `useWsJobs().lastJobUpdate`
 * and *intentionally* does not also set `lastEvent` for them (see
 * `test_WsProvider_onmessageJobUpdate_doesNotSetLastEvent` in
 * `__tests__/lib/ws.test.ts`) — changing that would alter already-asserted
 * WsProvider behavior. The `download.*` rule below is kept in the registry
 * for forward-compatibility (e.g. if the relay ever forwards `event` through
 * `job_update` too) and is independently unit-tested, but in the current
 * wiring per-gallery / dashboard download refresh is handled locally by
 * consumers that already have `lastJobUpdate` (or `gallery_id` from job
 * progress): `useDownloadJobs`, `useDownloadStats` (`hooks/useDownloadQueue.ts`),
 * `useInfiniteLibraryGalleries` (`hooks/useGalleries.ts`), and the reader
 * page's own WS-aware "still downloading" refresh.
 */

import { useEffect } from 'react'
import { mutate as globalMutate } from 'swr'
import { useWsEvents } from './ws'
import type { WsEventPayload, WsMessage } from './types'

export type SwrKey = string | readonly unknown[] | null | undefined

/** True when a string key, or the first element of an array key, starts with `prefix`. */
function keyHasPrefix(key: SwrKey, prefix: string): boolean {
  if (typeof key === 'string') return key.startsWith(prefix)
  if (Array.isArray(key)) return typeof key[0] === 'string' && key[0].startsWith(prefix)
  return false
}

interface InvalidationRule {
  /** Matches against the EventBus `event_type` (e.g. `"gallery.updated"`). */
  matchesEvent: (eventType: string) => boolean
  /** SWR key filter — same shape SWR's global `mutate(filter)` expects. */
  keyFilter: (key: SwrKey) => boolean
}

const RULES: InvalidationRule[] = [
  {
    // download.* (download_job resource) — dashboard recent-jobs widget +
    // this gallery's reader/library image caches, when the job progress
    // carries gallery info. See module docstring: currently unreachable via
    // lastEvent, kept for forward-compatibility and unit-tested directly.
    matchesEvent: (eventType) => eventType.startsWith('download.'),
    keyFilter: (key) =>
      keyHasPrefix(key, 'dashboard/jobs') ||
      keyHasPrefix(key, 'download/jobs') ||
      keyHasPrefix(key, 'download/stats') ||
      keyHasPrefix(key, 'library/gallery') ||
      keyHasPrefix(key, 'gallery/images') ||
      keyHasPrefix(key, 'gallery/progress'),
  },
  {
    // import.* / gallery.* — library listings + this gallery's detail/images cache.
    matchesEvent: (eventType) => eventType.startsWith('import.') || eventType.startsWith('gallery.'),
    keyFilter: (key) =>
      keyHasPrefix(key, 'library/') || keyHasPrefix(key, 'gallery/') || keyHasPrefix(key, 'dashboard/recent'),
  },
  {
    // subscription.* / subscription_group.* — excludes subscription.checked,
    // which already has a dedicated `lastSubCheck` context consumed
    // directly by app/subscriptions/page.tsx.
    matchesEvent: (eventType) => eventType.startsWith('subscription') && eventType !== 'subscription.checked',
    keyFilter: (key) => keyHasPrefix(key, 'subscriptions') || keyHasPrefix(key, 'subscription-groups'),
  },
  {
    // collection.* — collections list + the open collection's gallery members
    // (keyed under 'collections' and 'collection'). Emitted by
    // routers/collections.py on create/rename/reorder/membership changes.
    matchesEvent: (eventType) => eventType.startsWith('collection.'),
    keyFilter: (key) =>
      keyHasPrefix(key, 'collections') || keyHasPrefix(key, 'collection'),
  },
  {
    // dataset.* — dataset list + the open dataset's members/captions (keyed
    // under 'dataset'/'datasets'). Focus revalidation remains a missed-event
    // fallback, while this rule surfaces captioning updates immediately.
    matchesEvent: (eventType) => eventType.startsWith('dataset.'),
    keyFilter: (key) => keyHasPrefix(key, 'dataset'),
  },
  {
    // tags.* — the tags admin page (tags / tag-anomalies / translations) plus
    // the affected gallery's detail/images tag display. TAGS_UPDATED carries
    // resource_type "gallery" on add/remove and "tag" on rename/merge.
    matchesEvent: (eventType) => eventType.startsWith('tags.'),
    keyFilter: (key) =>
      keyHasPrefix(key, 'tag') ||
      keyHasPrefix(key, 'library/gallery') ||
      keyHasPrefix(key, 'gallery/'),
  },
]

/** Returns the SWR key filter for a given EventBus `event_type`, or null if unmapped. */
export function resolveInvalidationFilter(
  eventType: string | undefined | null,
): ((key: SwrKey) => boolean) | null {
  if (!eventType) return null
  const rule = RULES.find((r) => r.matchesEvent(eventType))
  return rule ? rule.keyFilter : null
}

/** Extracts the lossless EventBus payload carried on a raw WS message, if any. */
export function extractEventPayload(msg: WsMessage | null | undefined): WsEventPayload | null {
  if (!msg) return null
  if (msg.event) return msg.event
  if (msg.event_type) {
    return {
      event_type: msg.event_type,
      resource_type: msg.resource_type ?? null,
      resource_id: msg.resource_id ?? null,
      data: msg.data ?? {},
    }
  }
  return null
}

/**
 * Bridges WS EventBus events to SWR cache invalidation. Mount once inside
 * `WsProvider` (see `components/LayoutShell.tsx`) — it renders nothing.
 */
export function WsInvalidationBridge(): null {
  const { lastEvent } = useWsEvents()

  useEffect(() => {
    const payload = extractEventPayload(lastEvent)
    if (!payload) return
    const filter = resolveInvalidationFilter(payload.event_type)
    if (!filter) return
    void globalMutate(filter)
  }, [lastEvent])

  return null
}
