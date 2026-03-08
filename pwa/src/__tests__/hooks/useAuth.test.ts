/**
 * useAuth — Vitest test suite
 *
 * Covers:
 *   login()  — calls api.auth.login with the supplied username and password
 *   login()  — navigates to "/" and refreshes the router on success
 *   login()  — propagates errors thrown by api.auth.login (does not swallow)
 *   logout() — calls api.auth.logout
 *   logout() — navigates to "/login" and refreshes the router on success
 *   logout() — does NOT navigate when api.auth.logout throws (shows toast instead)
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations, so any variables
 *   referenced inside a factory must be declared with vi.hoisted() to guarantee
 *   they exist at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockPush, mockRefresh, mockLogin, mockLogout, mockToastError, mockMutate } = vi.hoisted(
  () => ({
    mockPush: vi.fn(),
    mockRefresh: vi.fn(),
    mockLogin: vi.fn(),
    mockLogout: vi.fn(),
    mockToastError: vi.fn(),
    mockMutate: vi.fn(),
  }),
)

// ── Module mocks ──────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
}))

vi.mock('sonner', () => ({
  toast: { error: mockToastError },
}))

vi.mock('swr', () => ({
  default: vi.fn(),
  mutate: mockMutate,
}))

vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      login: mockLogin,
      logout: mockLogout,
    },
  },
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useAuth } from '@/hooks/useAuth'

// ── Shared setup ──────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockLogin.mockResolvedValue({ status: 'ok', role: 'admin' })
  mockLogout.mockResolvedValue({ status: 'ok' })
  mockMutate.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useAuth — login()', () => {
  it('should call api.auth.login with the supplied username and password', async () => {
    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.login('alice', 'secret123')
    })

    expect(mockLogin).toHaveBeenCalledOnce()
    expect(mockLogin).toHaveBeenCalledWith('alice', 'secret123')
  })

  it('should navigate to "/" after a successful login', async () => {
    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.login('alice', 'secret123')
    })

    expect(mockPush).toHaveBeenCalledWith('/')
  })

  it('should call router.refresh() after a successful login', async () => {
    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.login('alice', 'secret123')
    })

    expect(mockRefresh).toHaveBeenCalledOnce()
  })

  it('should propagate errors thrown by api.auth.login without catching them', async () => {
    mockLogin.mockRejectedValue(new Error('Invalid credentials'))

    const { result } = renderHook(() => useAuth())

    await expect(
      act(async () => {
        await result.current.login('alice', 'wrong')
      }),
    ).rejects.toThrow('Invalid credentials')

    // Navigation must NOT happen when login fails.
    expect(mockPush).not.toHaveBeenCalled()
  })
})

describe('useAuth — logout()', () => {
  it('should call api.auth.logout exactly once', async () => {
    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.logout()
    })

    expect(mockLogout).toHaveBeenCalledOnce()
  })

  it('should invalidate the SWR cache after a successful logout', async () => {
    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.logout()
    })

    // mutate(() => true, undefined, { revalidate: false }) clears all SWR cache entries.
    expect(mockMutate).toHaveBeenCalledOnce()
  })

  it('should navigate to "/login" after a successful logout', async () => {
    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.logout()
    })

    expect(mockPush).toHaveBeenCalledWith('/login')
  })

  it('should call router.refresh() after a successful logout', async () => {
    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.logout()
    })

    expect(mockRefresh).toHaveBeenCalledOnce()
  })

  it('should show a toast error and not navigate when api.auth.logout throws', async () => {
    mockLogout.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.logout()
    })

    // The hook catches the error internally and shows a toast.
    expect(mockToastError).toHaveBeenCalledOnce()

    // Navigation must NOT happen when logout fails.
    expect(mockPush).not.toHaveBeenCalled()
    expect(mockMutate).not.toHaveBeenCalled()
  })
})
