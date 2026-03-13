import useSWR, { useSWRConfig } from 'swr'
import useSWRMutation from 'swr/mutation'
import { useEffect, useRef } from 'react'
import { api } from '@/lib/api'
import { useWs } from '@/lib/ws'
import type { JobListParams } from '@/lib/types'

const THROTTLE_MS = 1000

export function useDownloadJobs(params: JobListParams = {}) {
  const { connected, lastJobUpdate } = useWs()
  const { mutate } = useSWRConfig()
  const lastFiredRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    if (!lastJobUpdate) return
    const now = Date.now()
    const elapsed = now - lastFiredRef.current
    if (elapsed >= THROTTLE_MS) {
      lastFiredRef.current = now
      mutate(['download/jobs', params])
    } else {
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        lastFiredRef.current = Date.now()
        mutate(['download/jobs', params])
      }, THROTTLE_MS - elapsed)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastJobUpdate])

  return useSWR(['download/jobs', params], () => api.download.getJobs(params), {
    refreshInterval: connected ? 0 : 3000,
    dedupingInterval: 2000,
    focusThrottleInterval: 5000,
  })
}

export function useEnqueueDownload() {
  return useSWRMutation('download/enqueue', (_key: unknown, { arg }: { arg: { url: string } }) =>
    api.download.enqueue(arg.url),
  )
}

export function useCancelJob() {
  return useSWRMutation('download/cancel', (_key: unknown, { arg }: { arg: string }) =>
    api.download.cancelJob(arg),
  )
}

export function useClearFinishedJobs() {
  return useSWRMutation('download/clear', () => api.download.clearFinishedJobs())
}

export function useDownloadStats() {
  const { connected, lastJobUpdate } = useWs()
  const { mutate } = useSWRConfig()
  const lastFiredRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    if (!lastJobUpdate) return
    const now = Date.now()
    const elapsed = now - lastFiredRef.current
    if (elapsed >= THROTTLE_MS) {
      lastFiredRef.current = now
      mutate('download/stats')
    } else {
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        lastFiredRef.current = Date.now()
        mutate('download/stats')
      }, THROTTLE_MS - elapsed)
    }
  }, [lastJobUpdate, mutate])

  return useSWR('download/stats', () => api.download.getStats(), {
    refreshInterval: connected ? 0 : 5000,
    dedupingInterval: 3000,
  })
}

export function usePauseJob() {
  return useSWRMutation(
    'download/pause',
    (_key: unknown, { arg }: { arg: { id: string; action: 'pause' | 'resume' } }) =>
      arg.action === 'pause' ? api.download.pauseJob(arg.id) : api.download.resumeJob(arg.id),
  )
}

export function useRetryJob() {
  const { mutate: globalMutate } = useSWRConfig()
  return useSWRMutation('download/retry', async (_key: unknown, { arg }: { arg: string }) => {
    const result = await api.download.retryJob(arg)
    globalMutate((key: unknown) => typeof key === 'string' && key.startsWith('download/'))
    return result
  })
}

export function useCheckUrl(url: string) {
  const trimmed = url.trim()
  return useSWR(
    trimmed.length > 5 ? ['download/check-url', trimmed] : null,
    () => api.download.checkUrl(trimmed),
    {
      dedupingInterval: 5000,
      keepPreviousData: true,
    },
  )
}

export function useSupportedSites() {
  return useSWR('download/supported-sites', () => api.download.supportedSites(), {
    dedupingInterval: 60000,
    revalidateOnFocus: false,
  })
}
