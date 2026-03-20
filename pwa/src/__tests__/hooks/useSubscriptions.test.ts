/**
 * useSubscriptions — Vitest test suite
 *
 * Covers:
 *   useSubscriptions       — passes key ['subscriptions', JSON.stringify(params)] to useSWR
 *   useSubscriptions       — fetcher calls api.subscriptions.list with params
 *   useCreateSubscription  — trigger calls api.subscriptions.create with arg
 *   useUpdateSubscription  — trigger calls api.subscriptions.update with id and data
 *   useDeleteSubscription  — trigger calls api.subscriptions.delete with id
 *   useCheckSubscription   — trigger calls api.subscriptions.check with id
 *   useSubscriptionJobs    — passes null key when subId is null
 *   useSubscriptionJobs    — passes key with subId and refreshInterval: 5000 when subId set
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockList, mockCreate, mockUpdate, mockDelete, mockCheck, mockJobs } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockUpdate: vi.fn(),
  mockDelete: vi.fn(),
  mockCheck: vi.fn(),
  mockJobs: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    subscriptions: {
      list: mockList,
      create: mockCreate,
      update: mockUpdate,
      delete: mockDelete,
      check: mockCheck,
      jobs: mockJobs,
    },
  },
}))

// ── swr / swr/mutation mocks ──────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

const { mockUseSWR, mockUseSWRMutation } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: true, error: undefined }
    },
  ),
  mockUseSWRMutation: vi.fn(
    (_key: unknown, fetcher: (_k: unknown, extra: { arg: unknown }) => unknown) => ({
      trigger: (arg: unknown) => fetcher(_key, { arg }),
      isMutating: false,
    }),
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

vi.mock('swr/mutation', () => ({
  default: mockUseSWRMutation,
}))

// ── Import hooks after mocks ──────────────────────────────────────────

import {
  useSubscriptions,
  useCreateSubscription,
  useUpdateSubscription,
  useDeleteSubscription,
  useCheckSubscription,
  useSubscriptionJobs,
} from '@/hooks/useSubscriptions'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockList.mockResolvedValue({ items: [], total: 0 })
  mockCreate.mockResolvedValue({ id: 1 })
  mockUpdate.mockResolvedValue({ id: 1 })
  mockDelete.mockResolvedValue({})
  mockCheck.mockResolvedValue({ status: 'ok' })
  mockJobs.mockResolvedValue({ jobs: [] })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useSubscriptions', () => {
  it('test_useSubscriptions_key_firstElementIsSubscriptions', () => {
    useSubscriptions()
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('subscriptions')
  })

  it('test_useSubscriptions_key_secondElementIsJsonStringifiedParams', () => {
    const params = { source: 'pixiv', enabled: true }
    useSubscriptions(params)
    const { key } = lastSwrCall()
    expect((key as unknown[])[1]).toBe(JSON.stringify(params))
  })

  it('test_useSubscriptions_fetcher_callsApiSubscriptionsListWithParams', async () => {
    const params = { limit: 20, offset: 0 }
    useSubscriptions(params)
    await lastSwrCall().fetcher!()
    expect(mockList).toHaveBeenCalledWith(params)
  })
})

describe('useCreateSubscription', () => {
  it('test_useCreateSubscription_key_isSubscriptions', () => {
    useCreateSubscription()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('subscriptions')
  })

  it('test_useCreateSubscription_trigger_callsApiSubscriptionsCreate', async () => {
    const { trigger } = useCreateSubscription()
    const arg = { url: 'https://pixiv.net/user/123', name: 'Test', auto_download: true }
    await trigger(arg)
    expect(mockCreate).toHaveBeenCalledWith(arg)
  })
})

describe('useUpdateSubscription', () => {
  it('test_useUpdateSubscription_key_isSubscriptions', () => {
    useUpdateSubscription()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('subscriptions')
  })

  it('test_useUpdateSubscription_trigger_callsApiSubscriptionsUpdateWithIdAndData', async () => {
    const { trigger } = useUpdateSubscription()
    await trigger({ id: 42, data: { enabled: false, name: 'Updated' } })
    expect(mockUpdate).toHaveBeenCalledWith(42, { enabled: false, name: 'Updated' })
  })
})

describe('useDeleteSubscription', () => {
  it('test_useDeleteSubscription_key_isSubscriptions', () => {
    useDeleteSubscription()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('subscriptions')
  })

  it('test_useDeleteSubscription_trigger_callsApiSubscriptionsDeleteWithId', async () => {
    const { trigger } = useDeleteSubscription()
    await trigger(7)
    expect(mockDelete).toHaveBeenCalledWith(7)
  })
})

describe('useCheckSubscription', () => {
  it('test_useCheckSubscription_trigger_callsApiSubscriptionsCheckWithId', async () => {
    const { trigger } = useCheckSubscription()
    await trigger(99)
    expect(mockCheck).toHaveBeenCalledWith(99)
  })
})

describe('useSubscriptionJobs', () => {
  it('test_useSubscriptionJobs_nullSubId_passesNullKeyToSwr', () => {
    useSubscriptionJobs(null)
    expect(lastSwrCall().key).toBeNull()
  })

  it('test_useSubscriptionJobs_validSubId_passesArrayKeyWithSubId', () => {
    useSubscriptionJobs(3)
    const { key } = lastSwrCall()
    expect(Array.isArray(key)).toBe(true)
    expect((key as unknown[])[0]).toBe('subscription-jobs')
    expect((key as unknown[])[1]).toBe(3)
  })

  it('test_useSubscriptionJobs_validSubId_setsRefreshInterval5000', () => {
    useSubscriptionJobs(5)
    expect(lastSwrCall().options.refreshInterval).toBe(5000)
  })

  it('test_useSubscriptionJobs_validSubId_fetcher_callsApiSubscriptionsJobs', async () => {
    useSubscriptionJobs(11)
    await lastSwrCall().fetcher!()
    expect(mockJobs).toHaveBeenCalledWith(11)
  })
})
