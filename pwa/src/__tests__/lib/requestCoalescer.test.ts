import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRequestCoalescer } from '@/lib/requestCoalescer'

afterEach(() => vi.useRealTimers())

describe('createRequestCoalescer', () => {
  it('coalesces an in-flight burst into one trailing request', async () => {
    vi.useFakeTimers()
    let resolveFirst: (() => void) | undefined
    const task = vi
      .fn<() => Promise<void>>()
      .mockImplementationOnce(() => new Promise<void>((resolve) => (resolveFirst = resolve)))
      .mockResolvedValue(undefined)
    const coalescer = createRequestCoalescer(task, 1000)
    coalescer.trigger()
    coalescer.trigger()
    coalescer.trigger()
    expect(task).toHaveBeenCalledTimes(1)
    resolveFirst?.()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(1000)
    expect(task).toHaveBeenCalledTimes(2)
  })

  it('cancel prevents a queued trailing request', async () => {
    vi.useFakeTimers()
    const task = vi.fn<() => Promise<void>>().mockResolvedValue(undefined)
    const coalescer = createRequestCoalescer(task, 1000)
    coalescer.trigger()
    await Promise.resolve()
    coalescer.trigger()
    coalescer.cancel()
    await vi.runAllTimersAsync()
    expect(task).toHaveBeenCalledTimes(1)
  })
})
