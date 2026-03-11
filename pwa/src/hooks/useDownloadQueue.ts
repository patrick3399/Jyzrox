import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'
import type { JobListParams } from '@/lib/types'

export function useDownloadJobs(params: JobListParams = {}) {
  return useSWR(['download/jobs', params], () => api.download.getJobs(params), {
    refreshInterval: 3000,
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
  return useSWR('download/stats', () => api.download.getStats(), {
    refreshInterval: 5000,
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
