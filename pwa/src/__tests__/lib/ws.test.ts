/**
 * ws.tsx — Vitest test suite
 *
 * Covers:
 *   useWs / useWebSocket  — return context defaults when called outside a provider
 *   WsProvider            — renders children
 *   WsProvider            — dismissAlert removes the alert at the given index
 *   WsProvider            — onmessage 'alert' appends to alerts array
 *   WsProvider            — onmessage 'job_update' sets lastJobUpdate
 *   WsProvider            — onmessage 'subscription_checked' sets lastSubCheck
 *   WsProvider            — malformed JSON in onmessage is swallowed gracefully
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import React from 'react'

// ── WebSocket mock ─────────────────────────────────────────────────────
// Capture the last constructed WebSocket so tests can fire events directly.

interface MockWebSocket {
  onopen: ((ev: Event) => void) | null
  onmessage: ((ev: { data: string }) => void) | null
  onclose: ((ev: Event) => void) | null
  onerror: ((ev: Event) => void) | null
  close: () => void
  readyState: number
}

let mockWsInstance: MockWebSocket | null = null

class FakeWebSocket {
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  readyState = 0
  close = vi.fn(() => {
    if (this.onclose) this.onclose({} as Event)
  })

  constructor(_url: string) {
    mockWsInstance = this
  }
}

vi.stubGlobal('WebSocket', FakeWebSocket)

// Provide a minimal window.location if not present (jsdom usually does).
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { protocol: 'http:', host: 'localhost' },
  })
}

// ── Import after global stubs ──────────────────────────────────────────

import {
  WsProvider,
  useWs,
  useWebSocket,
  useWsConnection,
  useWsJobs,
  useWsAlerts,
  useWsEvents,
  useWsLogs,
} from '@/lib/ws'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  mockWsInstance = null
  vi.clearAllMocks()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useWs default context (outside provider)', () => {
  it('test_useWs_outsideProvider_connectedIsFalse', () => {
    const { result } = renderHook(() => useWs())
    expect(result.current.connected).toBe(false)
  })

  it('test_useWs_outsideProvider_alertsIsEmptyArray', () => {
    const { result } = renderHook(() => useWs())
    expect(result.current.alerts).toEqual([])
  })

  it('test_useWs_outsideProvider_lastJobUpdateIsNull', () => {
    const { result } = renderHook(() => useWs())
    expect(result.current.lastJobUpdate).toBeNull()
  })

  it('test_useWs_outsideProvider_lastEventIsNull', () => {
    const { result } = renderHook(() => useWs())
    expect(result.current.lastEvent).toBeNull()
  })

  it('test_useWebSocket_isAliasForUseWs_returnsSameShape', () => {
    const { result } = renderHook(() => useWebSocket())
    expect(result.current).toHaveProperty('connected')
    expect(result.current).toHaveProperty('alerts')
    expect(result.current).toHaveProperty('lastJobUpdate')
    expect(result.current).toHaveProperty('lastSubCheck')
    expect(result.current).toHaveProperty('lastEvent')
  })
})

describe('WsProvider', () => {
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(WsProvider, null, children)

  it('test_WsProvider_rendersChildren', () => {
    const { result } = renderHook(() => useWs(), { wrapper })
    // If the provider renders children correctly the hook call will succeed
    expect(result.current).toBeDefined()
  })

  it('test_WsProvider_onmessageAlert_appendsToAlerts', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({ data: JSON.stringify({ type: 'alert', message: 'Hello!' }) })
    })

    expect(result.current.alerts).toContain('Hello!')
  })

  it('test_WsProvider_onmessageJobUpdate_setsLastJobUpdate', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({
          type: 'job_update',
          job_id: 'job-1',
          status: 'running',
          progress: { done: 5, total: 10 },
        }),
      })
    })

    expect(result.current.lastJobUpdate).toEqual({
      job_id: 'job-1',
      status: 'running',
      progress: { done: 5, total: 10 },
    })
  })

  it('test_WsProvider_onmessageSubscriptionChecked_setsLastSubCheck', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({
          type: 'subscription_checked',
          sub_id: 42,
          status: 'done',
          new_works: 3,
          job_id: 'job-2',
        }),
      })
    })

    expect(result.current.lastSubCheck).toEqual({
      sub_id: 42,
      status: 'done',
      new_works: 3,
      job_id: 'job-2',
    })
  })

  it('test_WsProvider_malformedJson_isSwallowedGracefully', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    // This should not throw
    await act(async () => {
      mockWsInstance?.onmessage?.({ data: 'not valid json{{{' })
    })

    // State remains at defaults
    expect(result.current.lastJobUpdate).toBeNull()
    expect(result.current.alerts).toEqual([])
  })

  it('test_WsProvider_onmessageNewEventType_setsLastEvent', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({
          type: 'gallery.deleted',
          event_type: 'gallery.deleted',
          resource_type: 'gallery',
          resource_id: 42,
          data: {},
        }),
      })
    })

    expect(result.current.lastEvent).toBeTruthy()
    expect(result.current.lastEvent?.type).toBe('gallery.deleted')
    expect(result.current.lastEvent?.resource_id).toBe(42)
  })

  it('test_WsProvider_onmessagePing_doesNotSetLastEvent', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({ type: 'ping', ts: '2024-01-01T00:00:00Z' }),
      })
    })

    expect(result.current.lastEvent).toBeNull()
  })

  it('test_WsProvider_onmessageJobUpdate_doesNotSetLastEvent', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({
          type: 'job_update',
          job_id: 'j1',
          status: 'done',
        }),
      })
    })

    // lastJobUpdate should be set, but lastEvent should NOT
    expect(result.current.lastJobUpdate).toBeTruthy()
    expect(result.current.lastEvent).toBeNull()
  })

  it('test_WsProvider_dismissAlert_removesAlertAtIndex', async () => {
    const { result } = renderHook(() => useWs(), { wrapper })

    // Add two alerts
    await act(async () => {
      mockWsInstance?.onmessage?.({ data: JSON.stringify({ type: 'alert', message: 'First' }) })
      mockWsInstance?.onmessage?.({ data: JSON.stringify({ type: 'alert', message: 'Second' }) })
    })

    expect(result.current.alerts).toHaveLength(2)

    // Dismiss the first one (index 0)
    await act(async () => {
      result.current.dismissAlert(0)
    })

    expect(result.current.alerts).toHaveLength(1)
    expect(result.current.alerts[0]).toBe('Second')
  })
})

describe('focused hooks — granular context isolation', () => {
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(WsProvider, null, children)

  it('test_useWsConnection_outsideProvider_connectedIsFalse', () => {
    const { result } = renderHook(() => useWsConnection())
    expect(result.current.connected).toBe(false)
  })

  it('test_useWsJobs_outsideProvider_returnsNulls', () => {
    const { result } = renderHook(() => useWsJobs())
    expect(result.current.lastJobUpdate).toBeNull()
    expect(result.current.lastSubCheck).toBeNull()
  })

  it('test_useWsAlerts_outsideProvider_returnsEmptyArray', () => {
    const { result } = renderHook(() => useWsAlerts())
    expect(result.current.alerts).toEqual([])
  })

  it('test_useWsEvents_outsideProvider_returnsNull', () => {
    const { result } = renderHook(() => useWsEvents())
    expect(result.current.lastEvent).toBeNull()
  })

  it('test_useWsLogs_outsideProvider_returnsNull', () => {
    const { result } = renderHook(() => useWsLogs())
    expect(result.current.lastLogEntry).toBeNull()
  })

  it('test_useWsConnection_insideProvider_connectedStartsFalse', () => {
    const { result } = renderHook(() => useWsConnection(), { wrapper })
    expect(result.current.connected).toBe(false)
  })

  it('test_useWsJobs_onmessageJobUpdate_setsLastJobUpdate', async () => {
    const { result } = renderHook(() => useWsJobs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({
          type: 'job_update',
          job_id: 'j-99',
          status: 'done',
          progress: null,
        }),
      })
    })

    expect(result.current.lastJobUpdate?.job_id).toBe('j-99')
    expect(result.current.lastJobUpdate?.status).toBe('done')
  })

  it('test_useWsJobs_onmessageSubscriptionChecked_setsLastSubCheck', async () => {
    const { result } = renderHook(() => useWsJobs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({
          type: 'subscription_checked',
          sub_id: 7,
          status: 'checked',
          new_works: 1,
          job_id: null,
        }),
      })
    })

    expect(result.current.lastSubCheck?.sub_id).toBe(7)
  })

  it('test_useWsAlerts_onmessageAlert_appendsToAlerts', async () => {
    const { result } = renderHook(() => useWsAlerts(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({ data: JSON.stringify({ type: 'alert', message: 'Focused!' }) })
    })

    expect(result.current.alerts).toContain('Focused!')
  })

  it('test_useWsAlerts_dismissAlert_removesAlert', async () => {
    const { result } = renderHook(() => useWsAlerts(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({ data: JSON.stringify({ type: 'alert', message: 'A' }) })
      mockWsInstance?.onmessage?.({ data: JSON.stringify({ type: 'alert', message: 'B' }) })
    })
    expect(result.current.alerts).toHaveLength(2)

    await act(async () => {
      result.current.dismissAlert(0)
    })
    expect(result.current.alerts).toEqual(['B'])
  })

  it('test_useWsEvents_onmessageEventBusType_setsLastEvent', async () => {
    const { result } = renderHook(() => useWsEvents(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({ type: 'gallery.updated', resource_id: 5 }),
      })
    })

    expect(result.current.lastEvent?.type).toBe('gallery.updated')
  })

  it('test_useWsLogs_onmessageLogEntry_setsLastLogEntry', async () => {
    const logEntry = {
      id: 1,
      level: 'info',
      message: 'test log',
      source: 'worker',
      created_at: '2024-01-01T00:00:00Z',
    }
    const { result } = renderHook(() => useWsLogs(), { wrapper })

    await act(async () => {
      mockWsInstance?.onmessage?.({
        data: JSON.stringify({ type: 'log_entry', log: logEntry }),
      })
    })

    expect(result.current.lastLogEntry).toEqual(logEntry)
  })
})
