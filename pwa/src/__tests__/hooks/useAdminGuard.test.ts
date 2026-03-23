/**
 * useAdminGuard — Vitest test suite
 *
 * Covers:
 *   loading state — returns true when still loading (allows render during load)
 *   admin role    — returns true when user role is 'admin'
 *   member role   — returns false and calls router.replace('/settings')
 *   viewer role   — returns false and calls router.replace('/settings')
 *   custom fallback — uses custom fallback path when provided
 *   no redirect   — does NOT call router.replace when still loading
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations, so any variables
 *   referenced inside a factory must be declared with vi.hoisted() to guarantee
 *   they exist at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockReplace, mockProfileData, mockProfileLoading } = vi.hoisted(() => ({
  mockReplace: vi.fn(),
  mockProfileData: { current: undefined as { role: string } | undefined },
  mockProfileLoading: { current: false },
}))

// ── Module mocks ──────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({
    data: mockProfileData.current,
    isLoading: mockProfileLoading.current,
  }),
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useAdminGuard } from '@/hooks/useAdminGuard'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockProfileData.current = undefined
  mockProfileLoading.current = false
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useAdminGuard — loading state', () => {
  it('test_useAdminGuard_loading_returnsTrue', () => {
    mockProfileLoading.current = true
    mockProfileData.current = undefined

    const { result } = renderHook(() => useAdminGuard())

    expect(result.current).toBe(true)
  })

  it('test_useAdminGuard_loading_doesNotCallRouterReplace', () => {
    mockProfileLoading.current = true
    mockProfileData.current = undefined

    renderHook(() => useAdminGuard())

    expect(mockReplace).not.toHaveBeenCalled()
  })
})

describe('useAdminGuard — admin role', () => {
  it('test_useAdminGuard_adminRole_returnsTrue', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'admin' }

    const { result } = renderHook(() => useAdminGuard())

    expect(result.current).toBe(true)
  })

  it('test_useAdminGuard_adminRole_doesNotCallRouterReplace', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'admin' }

    renderHook(() => useAdminGuard())

    expect(mockReplace).not.toHaveBeenCalled()
  })
})

describe('useAdminGuard — non-admin roles', () => {
  it('test_useAdminGuard_memberRole_returnsFalse', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'member' }

    const { result } = renderHook(() => useAdminGuard())

    expect(result.current).toBe(false)
  })

  it('test_useAdminGuard_memberRole_callsRouterReplaceWithDefaultFallback', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'member' }

    renderHook(() => useAdminGuard())

    expect(mockReplace).toHaveBeenCalledWith('/settings')
  })

  it('test_useAdminGuard_viewerRole_returnsFalse', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'viewer' }

    const { result } = renderHook(() => useAdminGuard())

    expect(result.current).toBe(false)
  })

  it('test_useAdminGuard_viewerRole_callsRouterReplaceWithDefaultFallback', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'viewer' }

    renderHook(() => useAdminGuard())

    expect(mockReplace).toHaveBeenCalledWith('/settings')
  })
})

describe('useAdminGuard — custom fallback path', () => {
  it('test_useAdminGuard_customFallback_memberRole_redirectsToCustomPath', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'member' }

    renderHook(() => useAdminGuard('/dashboard'))

    expect(mockReplace).toHaveBeenCalledWith('/dashboard')
  })

  it('test_useAdminGuard_customFallback_viewerRole_redirectsToCustomPath', () => {
    mockProfileLoading.current = false
    mockProfileData.current = { role: 'viewer' }

    renderHook(() => useAdminGuard('/home'))

    expect(mockReplace).toHaveBeenCalledWith('/home')
  })
})
