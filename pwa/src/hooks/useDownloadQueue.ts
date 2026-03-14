import useSWR, { useSWRConfig } from 'swr'
import useSWRMutation from 'swr/mutation'
import { useEffect, useRef } from 'react'
import { api } from '@/lib/api'
import { useWs } from '@/lib/ws'
import type { JobListParams } from '@/lib/types'

const THROTTLE_MS = 1000

export function useDownloadJobs(params: JobListParams = {}) {
  const { connected, lastJobUpdate, lastSubCheck } = useWs()
  const { mutate } = useSWRConfig()
  const lastFiredRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Refresh on job_update or subscription_checked (new job created by subscription)
  const trigger = lastJobUpdate || lastSubCheck
  useEffect(() => {
    if (!trigger) return
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
  }, [trigger])

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
  const { connected, lastJobUpdate, lastSubCheck } = useWs()
  const { mutate } = useSWRConfig()
  const lastFiredRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const trigger = lastJobUpdate || lastSubCheck
  useEffect(() => {
    if (!trigger) return
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
  }, [trigger, mutate])

  return useSWR('download/stats', () => api.download.getStats({ exclude_subscription: true }), {
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

export function useDownloadPreview(url: string) {
  const trimmed = url.trim()

  // Parse EH gallery URL
  const ehMatch = trimmed.match(/e[-x]hentai\.org\/g\/(\d+)\/([a-f0-9]+)/)
  // Parse Pixiv illust URL
  const pixivMatch = trimmed.match(/pixiv\.net\/.*artworks\/(\d+)/)

  const key = ehMatch
    ? ['download/preview/eh', ehMatch[1], ehMatch[2]]
    : pixivMatch
    ? ['download/preview/pixiv', pixivMatch[1]]
    : null

  return useSWR<import('@/lib/types').EhGallery | import('@/lib/types').PixivIllust>(
    key,
    () => {
      if (ehMatch) return api.eh.getGallery(Number(ehMatch[1]), ehMatch[2])
      if (pixivMatch) return api.pixiv.getIllust(Number(pixivMatch[1]))
      throw new Error('unreachable')
    },
    { dedupingInterval: 30000, keepPreviousData: true },
  )
}
