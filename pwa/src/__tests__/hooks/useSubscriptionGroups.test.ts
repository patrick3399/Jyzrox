/**
 * useSubscriptionGroups — Vitest test suite
 *
 * Covers:
 *   useSubscriptionGroups passes 'subscription-groups' key to useSWR
 *   useSubscriptionGroups fetcher calls api.subscriptionGroups.list
 *   useCreateGroup trigger calls api.subscriptionGroups.create with name/schedule/concurrency/priority
 *   useUpdateGroup trigger calls api.subscriptionGroups.update with id and data
 *   useDeleteGroup trigger calls api.subscriptionGroups.delete with id
 *   useRunGroup trigger calls api.subscriptionGroups.run with id
 *   usePauseGroup trigger calls api.subscriptionGroups.pause with id
 *   useResumeGroup trigger calls api.subscriptionGroups.resume with id
 *   useBulkMove trigger calls api.subscriptionGroups.bulkMove with sub_ids and group_id
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const {
  mockList,
  mockCreate,
  mockUpdate,
  mockDelete,
  mockRun,
  mockPause,
  mockResume,
  mockBulkMove,
} = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockUpdate: vi.fn(),
  mockDelete: vi.fn(),
  mockRun: vi.fn(),
  mockPause: vi.fn(),
  mockResume: vi.fn(),
  mockBulkMove: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    subscriptionGroups: {
      list: mockList,
      create: mockCreate,
      update: mockUpdate,
      delete: mockDelete,
      run: mockRun,
      pause: mockPause,
      resume: mockResume,
      bulkMove: mockBulkMove,
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
  useSubscriptionGroups,
  useCreateGroup,
  useUpdateGroup,
  useDeleteGroup,
  useRunGroup,
  usePauseGroup,
  useResumeGroup,
  useBulkMove,
} from '@/hooks/useSubscriptionGroups'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockList.mockResolvedValue({ groups: [] })
  mockCreate.mockResolvedValue({ id: 1 })
  mockUpdate.mockResolvedValue({ id: 1 })
  mockDelete.mockResolvedValue({})
  mockRun.mockResolvedValue({})
  mockPause.mockResolvedValue({})
  mockResume.mockResolvedValue({})
  mockBulkMove.mockResolvedValue({})
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useSubscriptionGroups', () => {
  it('test_useSubscriptionGroups_key_isSubscriptionGroups', () => {
    useSubscriptionGroups()
    const { key } = lastSwrCall()
    expect(key).toBe('subscription-groups')
  })

  it('test_useSubscriptionGroups_fetcher_callsApiSubscriptionGroupsList', async () => {
    useSubscriptionGroups()
    await lastSwrCall().fetcher!()
    expect(mockList).toHaveBeenCalledOnce()
  })
})

describe('useCreateGroup', () => {
  it('test_useCreateGroup_key_isSubscriptionGroups', () => {
    useCreateGroup()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('subscription-groups')
  })

  it('test_useCreateGroup_trigger_callsApiSubscriptionGroupsCreate', async () => {
    const { trigger } = useCreateGroup()
    const arg = { name: 'Weekly', schedule: '0 * * * *', concurrency: 2, priority: 1 }
    await trigger(arg)
    expect(mockCreate).toHaveBeenCalledWith(arg)
  })
})

describe('useUpdateGroup', () => {
  it('test_useUpdateGroup_key_isSubscriptionGroups', () => {
    useUpdateGroup()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('subscription-groups')
  })

  it('test_useUpdateGroup_trigger_callsApiSubscriptionGroupsUpdateWithIdAndData', async () => {
    const { trigger } = useUpdateGroup()
    await trigger({ id: 5, data: { name: 'Updated', enabled: false } })
    expect(mockUpdate).toHaveBeenCalledWith(5, { name: 'Updated', enabled: false })
  })
})

describe('useDeleteGroup', () => {
  it('test_useDeleteGroup_key_isSubscriptionGroups', () => {
    useDeleteGroup()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('subscription-groups')
  })

  it('test_useDeleteGroup_trigger_callsApiSubscriptionGroupsDeleteWithId', async () => {
    const { trigger } = useDeleteGroup()
    await trigger(3)
    expect(mockDelete).toHaveBeenCalledWith(3)
  })
})

describe('useRunGroup', () => {
  it('test_useRunGroup_trigger_callsApiSubscriptionGroupsRunWithId', async () => {
    const { trigger } = useRunGroup()
    await trigger(7)
    expect(mockRun).toHaveBeenCalledWith(7)
  })
})

describe('usePauseGroup', () => {
  it('test_usePauseGroup_trigger_callsApiSubscriptionGroupsPauseWithId', async () => {
    const { trigger } = usePauseGroup()
    await trigger(4)
    expect(mockPause).toHaveBeenCalledWith(4)
  })
})

describe('useResumeGroup', () => {
  it('test_useResumeGroup_trigger_callsApiSubscriptionGroupsResumeWithId', async () => {
    const { trigger } = useResumeGroup()
    await trigger(2)
    expect(mockResume).toHaveBeenCalledWith(2)
  })
})

describe('useBulkMove', () => {
  it('test_useBulkMove_key_isSubscriptions', () => {
    useBulkMove()
    const [key] = mockUseSWRMutation.mock.calls[0]
    expect(key).toBe('subscriptions')
  })

  it('test_useBulkMove_trigger_callsApiSubscriptionGroupsBulkMoveWithSubIdsAndGroupId', async () => {
    const { trigger } = useBulkMove()
    await trigger({ sub_ids: [1, 2, 3], group_id: 10 })
    expect(mockBulkMove).toHaveBeenCalledWith([1, 2, 3], 10)
  })

  it('test_useBulkMove_trigger_callsApiSubscriptionGroupsBulkMoveWithNullGroupId', async () => {
    const { trigger } = useBulkMove()
    await trigger({ sub_ids: [5, 6], group_id: null })
    expect(mockBulkMove).toHaveBeenCalledWith([5, 6], null)
  })
})
