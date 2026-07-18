/**
 * wsInvalidation.tsx — Vitest test suite
 *
 * Covers:
 *   resolveInvalidationFilter — gallery.* / import.* events resolve a filter matching library+gallery keys
 *   resolveInvalidationFilter — subscription.* events resolve a filter matching subscription keys
 *   resolveInvalidationFilter — subscription.checked is excluded (handled elsewhere via lastSubCheck)
 *   resolveInvalidationFilter — download.* events resolve a filter matching dashboard/queue + gallery keys
 *   resolveInvalidationFilter — unmapped event types return null (no catch-all invalidation)
 *   extractEventPayload — prefers the lossless `event` field when present
 *   extractEventPayload — falls back to top-level fields when `event` is absent
 *   extractEventPayload — returns null for messages with no event_type (e.g. ping)
 *   WsInvalidationBridge — calls global mutate with the resolved filter when a mapped event arrives
 *   WsInvalidationBridge — does not call mutate for an unmapped event
 *   WsInvalidationBridge — does not call mutate when lastEvent is null
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import React from 'react'
import type { WsMessage } from '@/lib/types'

const { mockMutate, mockUseWsEvents } = vi.hoisted(() => ({
  mockMutate: vi.fn(),
  mockUseWsEvents: vi.fn(),
}))

vi.mock('swr', () => ({
  mutate: mockMutate,
}))

vi.mock('@/lib/ws', () => ({
  useWsEvents: mockUseWsEvents,
}))

import { resolveInvalidationFilter, extractEventPayload, WsInvalidationBridge } from '@/lib/wsInvalidation'

beforeEach(() => {
  vi.clearAllMocks()
  mockUseWsEvents.mockReturnValue({ lastEvent: null })
})

// ── resolveInvalidationFilter ───────────────────────────────────────────

describe('resolveInvalidationFilter', () => {
  it('test_resolveInvalidationFilter_galleryUpdated_matchesLibraryAndGalleryKeys', () => {
    const filter = resolveInvalidationFilter('gallery.updated')
    expect(filter).not.toBeNull()
    expect(filter!(['library/gallery', 'ehentai', '123'])).toBe(true)
    expect(filter!(['gallery/images/infinite', 'ehentai', '123', {}])).toBe(true)
    expect(filter!('dashboard/recent')).toBe(true)
  })

  it('test_resolveInvalidationFilter_galleryUpdated_doesNotMatchUnrelatedKeys', () => {
    const filter = resolveInvalidationFilter('gallery.updated')
    expect(filter).not.toBeNull()
    expect(filter!('subscriptions')).toBe(false)
    expect(filter!(['subscription-groups'])).toBe(false)
    expect(filter!('dashboard/jobs')).toBe(false)
  })

  it('test_resolveInvalidationFilter_importCompleted_matchesLibraryKeys', () => {
    const filter = resolveInvalidationFilter('import.completed')
    expect(filter).not.toBeNull()
    expect(filter!(['library/gallery', 'local', 'abc'])).toBe(true)
  })

  it('test_resolveInvalidationFilter_subscriptionCreated_matchesSubscriptionKeys', () => {
    const filter = resolveInvalidationFilter('subscription.created')
    expect(filter).not.toBeNull()
    expect(filter!(['subscriptions', '{}'])).toBe(true)
    expect(filter!('subscription-groups')).toBe(true)
  })

  it('test_resolveInvalidationFilter_subscriptionGroupUpdated_matchesSubscriptionGroupKeys', () => {
    const filter = resolveInvalidationFilter('subscription_group.updated')
    expect(filter).not.toBeNull()
    expect(filter!('subscription-groups')).toBe(true)
  })

  it('test_resolveInvalidationFilter_subscriptionCreated_doesNotMatchLibraryKeys', () => {
    const filter = resolveInvalidationFilter('subscription.created')
    expect(filter).not.toBeNull()
    expect(filter!(['library/gallery', 'ehentai', '123'])).toBe(false)
  })

  it('test_resolveInvalidationFilter_subscriptionChecked_returnsNull', () => {
    // subscription.checked is handled directly by app/subscriptions/page.tsx
    // via the dedicated lastSubCheck context — the bridge must ignore it.
    expect(resolveInvalidationFilter('subscription.checked')).toBeNull()
  })

  it('test_resolveInvalidationFilter_downloadProgress_matchesDashboardAndGalleryKeys', () => {
    const filter = resolveInvalidationFilter('download.progress')
    expect(filter).not.toBeNull()
    expect(filter!('dashboard/jobs')).toBe(true)
    expect(filter!(['download/jobs', {}])).toBe(true)
    expect(filter!(['library/gallery', 'ehentai', '123'])).toBe(true)
  })

  it('test_resolveInvalidationFilter_collectionUpdated_matchesCollectionsKeys', () => {
    // Regression: collection.updated had no rule, so with page polling demoted
    // to a WS-disconnect fallback the collections list stayed stale until the
    // user navigated away and back.
    const filter = resolveInvalidationFilter('collection.updated')
    expect(filter).not.toBeNull()
    expect(filter!('collections')).toBe(true)
    expect(filter!(['collections', 5])).toBe(true)
    expect(filter!(['collection', 5, 0])).toBe(true)
    expect(filter!('subscriptions')).toBe(false)
    expect(filter!(['library/gallery', 'local', 'a'])).toBe(false)
  })

  it('test_resolveInvalidationFilter_datasetUpdated_matchesDatasetKeys', () => {
    // Regression: the datasets hooks use revalidateOnFocus:false, so without a
    // rule the captioning worker's dataset.updated never surfaced live.
    const filter = resolveInvalidationFilter('dataset.updated')
    expect(filter).not.toBeNull()
    expect(filter!('datasets')).toBe(true)
    expect(filter!(['dataset', 3])).toBe(true)
    expect(filter!('collections')).toBe(false)
  })

  it('test_resolveInvalidationFilter_tagsUpdated_matchesTagAndAffectedGalleryKeys', () => {
    // Regression: tags.updated had no rule, so tag add/remove/rename did not
    // refresh the tags admin page or the open gallery's tag display live.
    const filter = resolveInvalidationFilter('tags.updated')
    expect(filter).not.toBeNull()
    expect(filter!('tags')).toBe(true)
    expect(filter!('tags/autocomplete')).toBe(true)
    expect(filter!('tag-anomalies')).toBe(true)
    expect(filter!(['library/gallery', 'ehentai', '123'])).toBe(true)
    expect(filter!(['gallery/images', 'ehentai', '123'])).toBe(true)
    expect(filter!('subscriptions')).toBe(false)
  })

  it('test_resolveInvalidationFilter_unmappedEventType_returnsNull', () => {
    expect(resolveInvalidationFilter('dedup.scan_started')).toBeNull()
    expect(resolveInvalidationFilter('thumbnails.generated')).toBeNull()
  })

  it('test_resolveInvalidationFilter_nullOrUndefinedEventType_returnsNull', () => {
    expect(resolveInvalidationFilter(null)).toBeNull()
    expect(resolveInvalidationFilter(undefined)).toBeNull()
    expect(resolveInvalidationFilter('')).toBeNull()
  })
})

// ── extractEventPayload ──────────────────────────────────────────────────

describe('extractEventPayload', () => {
  it('test_extractEventPayload_prefersLosslessEventField', () => {
    const msg: WsMessage = {
      type: 'gallery.updated',
      event_type: 'gallery.updated',
      resource_type: 'gallery',
      resource_id: 5,
      event: {
        event_type: 'gallery.updated',
        resource_type: 'gallery',
        resource_id: 5,
        data: { title: 'from-event-field' },
      },
    }
    const payload = extractEventPayload(msg)
    expect(payload?.data).toEqual({ title: 'from-event-field' })
  })

  it('test_extractEventPayload_fallsBackToTopLevelFieldsWhenEventAbsent', () => {
    const msg: WsMessage = {
      type: 'gallery.updated',
      event_type: 'gallery.updated',
      resource_type: 'gallery',
      resource_id: 5,
      data: { title: 'top-level' },
    }
    const payload = extractEventPayload(msg)
    expect(payload).toEqual({
      event_type: 'gallery.updated',
      resource_type: 'gallery',
      resource_id: 5,
      data: { title: 'top-level' },
    })
  })

  it('test_extractEventPayload_pingMessage_returnsNull', () => {
    const msg: WsMessage = { type: 'ping', ts: '2024-01-01T00:00:00Z' }
    expect(extractEventPayload(msg)).toBeNull()
  })

  it('test_extractEventPayload_nullMessage_returnsNull', () => {
    expect(extractEventPayload(null)).toBeNull()
  })
})

// ── WsInvalidationBridge ──────────────────────────────────────────────────

describe('WsInvalidationBridge', () => {
  it('test_WsInvalidationBridge_mappedEvent_callsGlobalMutateWithResolvedFilter', () => {
    mockUseWsEvents.mockReturnValue({
      lastEvent: {
        type: 'gallery.updated',
        event_type: 'gallery.updated',
        resource_type: 'gallery',
        resource_id: 5,
        data: {},
      } satisfies WsMessage,
    })

    render(React.createElement(WsInvalidationBridge))

    expect(mockMutate).toHaveBeenCalledOnce()
    const filterArg = mockMutate.mock.calls[0][0] as (key: unknown) => boolean
    expect(filterArg(['library/gallery', 'ehentai', '123'])).toBe(true)
    expect(filterArg('subscriptions')).toBe(false)
  })

  it('test_WsInvalidationBridge_unmappedEvent_doesNotCallMutate', () => {
    mockUseWsEvents.mockReturnValue({
      lastEvent: {
        type: 'dedup.scan_started',
        event_type: 'dedup.scan_started',
        data: {},
      } satisfies WsMessage,
    })

    render(React.createElement(WsInvalidationBridge))

    expect(mockMutate).not.toHaveBeenCalled()
  })

  it('test_WsInvalidationBridge_nullLastEvent_doesNotCallMutate', () => {
    mockUseWsEvents.mockReturnValue({ lastEvent: null })

    render(React.createElement(WsInvalidationBridge))

    expect(mockMutate).not.toHaveBeenCalled()
  })

  it('test_WsInvalidationBridge_rendersNothing', () => {
    mockUseWsEvents.mockReturnValue({ lastEvent: null })

    const { container } = render(React.createElement(WsInvalidationBridge))

    expect(container).toBeEmptyDOMElement()
  })
})
