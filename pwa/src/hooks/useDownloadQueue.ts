import useSWR, { useSWRConfig } from 'swr'
import useSWRMutation from 'swr/mutation'
import { useEffect, useRef } from 'react'
import { api } from '@/lib/api'
import { useWs } from '@/lib/ws'
import type { JobListParams, DownloadPreview } from '@/lib/types'

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

  return useSWR<DownloadPreview | null>(
    trimmed.length > 10 ? ['download/preview', trimmed] : null,
    async (): Promise<DownloadPreview | null> => {
      try {
        const result = await api.download.preview(trimmed)
        if (result.preview_available) {
          return result
        }
      } catch {
        // Unified endpoint failed, try direct API calls as fallback
      }

      // Fallback to direct EH/Pixiv API calls
      const ehMatch = trimmed.match(/e[-x]hentai\.org\/g\/(\d+)\/([a-f0-9]+)/)
      if (ehMatch) {
        const data = await api.eh.getGallery(Number(ehMatch[1]), ehMatch[2])
        return {
          source: 'ehentai',
          preview_available: true,
          title: data.title,
          pages: data.pages,
          tags: data.tags,
          uploader: data.uploader,
          rating: data.rating,
          thumb_url: data.thumb,
          category: data.category,
        }
      }

      const pixivMatch = trimmed.match(/pixiv\.net\/.*artworks\/(\d+)/)
      if (pixivMatch) {
        const data = await api.pixiv.getIllust(Number(pixivMatch[1]))
        return {
          source: 'pixiv',
          preview_available: true,
          title: data.title,
          pages: data.page_count,
          tags: data.tags.map((t) => t.name),
          uploader: data.user?.name,
          thumb_url: data.image_urls?.square_medium,
        }
      }

      return null
    },
    { dedupingInterval: 30000, keepPreviousData: true },
  )
}
