import useSWR from 'swr'
import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '@/lib/api'
import { useWsLogs } from '@/lib/ws'
import type { LogEntry } from '@/lib/types'

interface LogParams {
  level?: string[]
  source?: string
  search?: string
  limit?: number
  offset?: number
}

export function useLogs(params: LogParams) {
  const key = JSON.stringify(['logs', params])
  const { data, error, isLoading, mutate } = useSWR(key, () => api.logs.list(params))
  return {
    logs: data?.logs ?? [],
    total: data?.total ?? 0,
    hasMore: data?.has_more ?? false,
    isLoading,
    error,
    mutate,
  }
}

export function useLogStream() {
  const { lastLogEntry } = useWsLogs()
  const [streamedLogs, setStreamedLogs] = useState<LogEntry[]>([])
  const [isPaused, setIsPaused] = useState(false)
  const pausedRef = useRef(false)

  useEffect(() => {
    pausedRef.current = isPaused
  }, [isPaused])

  useEffect(() => {
    if (lastLogEntry && !pausedRef.current) {
      setStreamedLogs((prev) => [lastLogEntry, ...prev].slice(0, 500))
    }
  }, [lastLogEntry])

  const clearStream = useCallback(() => setStreamedLogs([]), [])
  const togglePause = useCallback(() => setIsPaused((p) => !p), [])

  return { streamedLogs, clearStream, isPaused, togglePause }
}
