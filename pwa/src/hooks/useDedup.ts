'use client'

import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'
import type { RelationshipItem, DedupScanProgress } from '@/lib/types'
import { useState, useCallback, useRef } from 'react'

export function useDedupStats() {
  return useSWR('dedup-stats', () => api.dedup.getStats(), { refreshInterval: 30000 })
}

export function useDedupSettings() {
  return useSWR('dedup-features', () => api.settings.getFeatures())
}

export function useUpdateDedupSetting() {
  return useSWRMutation(
    'dedup-features',
    (_key: string, { arg }: { arg: { feature: string; enabled: boolean } }) =>
      api.settings.setFeature(arg.feature, arg.enabled),
  )
}

export function useUpdateDedupThreshold() {
  return useSWRMutation('dedup-features', (_key: string, { arg }: { arg: number }) =>
    api.settings.setFeatureValue('dedup_phash_threshold', arg),
  )
}

export function useDedupScanProgress() {
  const { data, mutate } = useSWR('dedup-scan-progress', () => api.dedup.getScanProgress(), {
    refreshInterval: (d) =>
      (d as DedupScanProgress | undefined)?.status === 'idle' ? 10_000 : 1_500,
    revalidateOnFocus: false,
  })
  const startScan = async (mode: 'reset' | 'pending') => {
    await api.dedup.startScan(mode)
    mutate()
  }
  const sendSignal = async (s: 'pause' | 'resume' | 'stop') => {
    await api.dedup.sendSignal(s)
    mutate()
  }
  return { progress: data ?? { status: 'idle' as const }, startScan, sendSignal }
}

// Cursor-based accumulating review list
export function useDedupReview(relationship?: string) {
  const [items, setItems] = useState<RelationshipItem[]>([])
  const cursorRef = useRef<string | undefined>(undefined)
  const generationRef = useRef(0)
  const [hasMore, setHasMore] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const load = useCallback(
    async (reset: boolean) => {
      const generation = reset ? ++generationRef.current : generationRef.current
      setIsLoading(true)
      try {
        const params: { relationship?: string; cursor?: string } = {}
        if (relationship) params.relationship = relationship
        if (!reset && cursorRef.current) params.cursor = cursorRef.current
        const res = await api.dedup.getReview(params)
        // Discard stale responses
        if (generation !== generationRef.current) return
        setItems((prev) => (reset ? res.items : [...prev, ...res.items]))
        cursorRef.current = res.next_cursor ?? undefined
        setHasMore(!!res.next_cursor)
      } catch {
        // ignore errors gracefully
      } finally {
        if (generation === generationRef.current) setIsLoading(false)
      }
    },
    [relationship],
  )

  const loadMore = useCallback(() => load(false), [load])

  const mutate = useCallback(() => {
    cursorRef.current = undefined
    setItems([])
    void load(true)
  }, [load])

  return { items, hasMore, loadMore, isLoading, mutate }
}
