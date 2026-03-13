'use client'
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { WsMessage } from './types'

export interface JobUpdateEvent {
  job_id: string
  status: string
  progress: Record<string, unknown> | null
}

export interface BatchUpdateEvent {
  sub_id: number
  sub_name: string | null
  total: number
  enqueued: number
  failed: number
  phase: 'enqueuing' | 'done'
}

interface WsContextValue {
  alerts: string[]
  connected: boolean
  dismissAlert: (index: number) => void
  lastJobUpdate: JobUpdateEvent | null
  lastBatchUpdate: BatchUpdateEvent | null
}

const WsContext = createContext<WsContextValue>({
  alerts: [],
  connected: false,
  dismissAlert: () => {},
  lastJobUpdate: null,
  lastBatchUpdate: null,
})

export function WsProvider({ children }: { children: React.ReactNode }) {
  const [alerts, setAlerts] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [lastJobUpdate, setLastJobUpdate] = useState<JobUpdateEvent | null>(null)
  const [lastBatchUpdate, setLastBatchUpdate] = useState<BatchUpdateEvent | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/api/ws`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (ev) => {
      try {
        const msg: WsMessage = JSON.parse(ev.data)
        if (msg.type === 'alert' && msg.message) {
          setAlerts((prev) => [...prev.slice(-49), msg.message!])
        } else if (msg.type === 'job_update' && msg.job_id) {
          setLastJobUpdate({
            job_id: msg.job_id,
            status: msg.status ?? '',
            progress: msg.progress ?? null,
          })
        } else if (msg.type === 'subscription_batch' && msg.sub_id) {
          setLastBatchUpdate({
            sub_id: msg.sub_id,
            sub_name: msg.sub_name ?? null,
            total: msg.total ?? 0,
            enqueued: msg.enqueued ?? 0,
            failed: msg.failed ?? 0,
            phase: msg.phase ?? 'enqueuing',
          })
        }
      } catch {
        /* ignore malformed */
      }
    }

    ws.onclose = () => {
      setConnected(false)
      if (!mountedRef.current) return
      clearTimeout(reconnectTimer.current)
      reconnectTimer.current = setTimeout(connect, 3000)
    }

    ws.onerror = (ev) => {
      if (process.env.NODE_ENV === 'development') {
        console.warn('[WebSocket] connection error', ev)
      }
      ws.close()
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const dismissAlert = useCallback((index: number) => {
    setAlerts((prev) => prev.filter((_, i) => i !== index))
  }, [])

  return (
    <WsContext.Provider value={{ alerts, connected, dismissAlert, lastJobUpdate, lastBatchUpdate }}>
      {children}
    </WsContext.Provider>
  )
}

export function useWs(): WsContextValue {
  return useContext(WsContext)
}

// Backward-compatible alias
export function useWebSocket(): WsContextValue {
  return useWs()
}
