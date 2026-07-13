import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { saveProgress } = vi.hoisted(() => ({
  saveProgress: vi.fn().mockResolvedValue({ status: 'ok' }),
}))

vi.mock('@/lib/api', () => ({
  api: { library: { saveProgress } },
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn() },
}))

import { useProgressSave } from '../components/Reader/hooks'

describe('useProgressSave', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    saveProgress.mockClear()
    saveProgress.mockResolvedValue({ status: 'ok' })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('debounces progress saves with the gallery source id', async () => {
    renderHook(() => useProgressSave('pixiv', '146240089', 11))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(saveProgress).toHaveBeenCalledWith('pixiv', '146240089', 11)
  })

  it('flushes the latest page with keepalive when the PWA is hidden', async () => {
    const { rerender } = renderHook(
      ({ page }) => useProgressSave('pixiv', '146240089', page),
      { initialProps: { page: 11 } },
    )
    rerender({ page: 12 })

    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'hidden',
    })
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    expect(saveProgress).toHaveBeenCalledWith('pixiv', '146240089', 12, { keepalive: true })
  })
})
