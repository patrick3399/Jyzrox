import useSWR from 'swr'
import { useEffect, useRef } from 'react'
import { api } from '@/lib/api'
import { useWsConnection, useWsJobs, useWsEvents } from '@/lib/ws'

const THROTTLE_MS = 2000

export function useDashboard() {
  const { connected } = useWsConnection()
  const { lastJobUpdate } = useWsJobs()
  const { lastEvent } = useWsEvents()
  const lastFiredRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const swr = useSWR('download/dashboard', () => api.download.getDashboard(), {
    refreshInterval: connected ? 0 : 5000,
    dedupingInterval: 2000,
    focusThrottleInterval: 5000,
  })

  // Trigger on semaphore_changed or download.* events
  const trigger = lastJobUpdate || (lastEvent?.type === 'semaphore_changed' ? lastEvent : null)
  useEffect(() => {
    if (!trigger) return
    const now = Date.now()
    const elapsed = now - lastFiredRef.current
    if (elapsed >= THROTTLE_MS) {
      lastFiredRef.current = now
      swr.mutate()
    } else {
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        lastFiredRef.current = Date.now()
        swr.mutate()
      }, THROTTLE_MS - elapsed)
    }
    return () => clearTimeout(timerRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger])

  return swr
}
