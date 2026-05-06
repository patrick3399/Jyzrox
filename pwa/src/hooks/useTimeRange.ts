import useSWR from 'swr'
import { api } from '@/lib/api'
import type { ImageTimeRangeResponse, TimelinePercentilesResponse } from '@/lib/types'

type SwrOpts = { signal?: AbortSignal }

interface UseTimeRangeParams {
  tags?: string[]
  exclude_tags?: string[]
  source?: string
  category?: string
  gallery_id?: number
}

export function useTimeRange(params: UseTimeRangeParams = {}) {
  const { data, error } = useSWR<ImageTimeRangeResponse>(
    ['library/images/time_range', params],
    (_: unknown, { signal }: SwrOpts = {}) => api.library.imageTimeRange(params, { signal }),
    { revalidateOnFocus: false, dedupingInterval: 300_000 },
  )

  return {
    minAt: data?.min_at ? new Date(data.min_at) : null,
    maxAt: data?.max_at ? new Date(data.max_at) : null,
    error,
  }
}

export function useTimelinePercentiles(params: UseTimeRangeParams = {}) {
  const { data } = useSWR<TimelinePercentilesResponse>(
    ['library/images/timeline_percentiles', params],
    (_: unknown, { signal }: SwrOpts = {}) => api.library.imageTimelinePercentiles(params, { signal }),
    { revalidateOnFocus: false, dedupingInterval: 300_000 },
  )

  return { percentiles: data?.timestamps ?? [] }
}
