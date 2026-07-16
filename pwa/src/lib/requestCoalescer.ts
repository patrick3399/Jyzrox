export interface RequestCoalescer {
  trigger: () => void
  cancel: () => void
}

/** Coalesce invalidation bursts into one request and one trailing refresh. */
export function createRequestCoalescer(
  task: () => Promise<void>,
  minIntervalMs: number,
): RequestCoalescer {
  let cancelled = false
  let inFlight = false
  let trailing = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let lastStartedAt = 0

  const run = async () => {
    timer = undefined
    if (cancelled) return
    if (inFlight) {
      trailing = true
      return
    }
    const wait = Math.max(0, minIntervalMs - (Date.now() - lastStartedAt))
    if (wait > 0) {
      if (!timer) timer = setTimeout(() => void run(), wait)
      return
    }
    inFlight = true
    lastStartedAt = Date.now()
    try {
      await task()
    } finally {
      inFlight = false
      if (trailing && !cancelled) {
        trailing = false
        const delay = Math.max(0, minIntervalMs - (Date.now() - lastStartedAt))
        timer = setTimeout(() => void run(), delay)
      }
    }
  }

  return {
    trigger() {
      if (cancelled) return
      if (inFlight) {
        trailing = true
        return
      }
      if (!timer) void run()
    },
    cancel() {
      cancelled = true
      if (timer) clearTimeout(timer)
      timer = undefined
    },
  }
}
