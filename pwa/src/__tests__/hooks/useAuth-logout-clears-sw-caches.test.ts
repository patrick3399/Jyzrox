import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const push = vi.fn()
const refresh = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, refresh }),
}))

const logoutApi = vi.fn()
vi.mock('@/lib/api', () => ({
  api: { auth: { login: vi.fn(), logout: (...args: unknown[]) => logoutApi(...args) } },
}))

const clearSWUserCaches = vi.fn()
vi.mock('@/lib/swCacheConfig', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/swCacheConfig')>()),
  clearSWUserCaches: (...args: unknown[]) => clearSWUserCaches(...args),
}))

import { useAuth } from '@/hooks/useAuth'

describe('useAuth logout SW cache clearing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('logout success clears service worker user caches so cached private media does not survive logout', async () => {
    logoutApi.mockResolvedValueOnce({ status: 'ok' })

    const { result } = renderHook(() => useAuth())
    await act(async () => {
      await result.current.logout()
    })

    expect(clearSWUserCaches).toHaveBeenCalledTimes(1)
    expect(push).toHaveBeenCalledWith('/login')
  })

  it('logout API failure keeps the session and does not clear caches', async () => {
    logoutApi.mockRejectedValueOnce(new Error('network'))

    const { result } = renderHook(() => useAuth())
    await act(async () => {
      await result.current.logout()
    })

    expect(clearSWUserCaches).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
  })
})
