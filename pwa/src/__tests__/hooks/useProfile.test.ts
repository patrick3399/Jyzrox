/**
 * useProfile — Vitest test suite
 *
 * Covers:
 *   useProfile — passes key 'auth/profile' to useSWR
 *   useProfile — configures revalidateOnFocus: false and dedupingInterval: 60000
 *   useProfile — fetcher calls api.auth.getProfile
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockGetProfile } = vi.hoisted(() => ({
  mockGetProfile: vi.fn(),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      getProfile: mockGetProfile,
    },
  },
}))

// ── swr mock ─────────────────────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []

const { mockUseSWR } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return { data: undefined, isLoading: true, error: undefined }
    },
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useProfile } from '@/hooks/useProfile'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockGetProfile.mockResolvedValue({ id: 1, username: 'admin', role: 'admin' })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastSwrCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useProfile', () => {
  it('test_useProfile_key_isAuthProfileString', () => {
    useProfile()
    expect(lastSwrCall().key).toBe('auth/profile')
  })

  it('test_useProfile_options_setsRevalidateOnFocusFalse', () => {
    useProfile()
    expect(lastSwrCall().options.revalidateOnFocus).toBe(false)
  })

  it('test_useProfile_options_setsDedupingInterval60000', () => {
    useProfile()
    expect(lastSwrCall().options.dedupingInterval).toBe(60000)
  })

  it('test_useProfile_fetcher_callsApiAuthGetProfile', async () => {
    useProfile()
    await lastSwrCall().fetcher!()
    expect(mockGetProfile).toHaveBeenCalledOnce()
  })
})
