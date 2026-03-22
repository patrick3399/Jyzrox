'use client'
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { WsMessage, LogEntry } from './types'

export interface JobUpdateEvent {
  job_id: string
  status: string
  progress: Record<string, unknown> | null
}

export interface SubCheckEvent {
  sub_id: number
  status: string
  new_works: number
  job_id: string | null
}

// ── Granular context types ─────────────────────────────────────────────

interface WsConnectionContextValue {
  connected: boolean
}

interface WsJobContextValue {
  lastJobUpdate: JobUpdateEvent | null
  lastSubCheck: SubCheckEvent | null
}

interface WsAlertContextValue {
  alerts: string[]
  dismissAlert: (index: number) => void
}

interface WsEventContextValue {
  lastEvent: WsMessage | null
}

interface WsLogContextValue {
  lastLogEntry: LogEntry | null
}

// ── Granular contexts ──────────────────────────────────────────────────

const WsConnectionContext = createContext<WsConnectionContextValue>({
  connected: false,
})

const WsJobContext = createContext<WsJobContextValue>({
  lastJobUpdate: null,
  lastSubCheck: null,
})

const WsAlertContext = createContext<WsAlertContextValue>({
  alerts: [],
  dismissAlert: () => {},
})

const WsEventContext = createContext<WsEventContextValue>({
  lastEvent: null,
})

const WsLogContext = createContext<WsLogContextValue>({
  lastLogEntry: null,
})

// ── Composite type (backward compat) ──────────────────────────────────

interface WsContextValue
  extends WsConnectionContextValue,
    WsJobContextValue,
    WsAlertContextValue,
    WsEventContextValue,
    WsLogContextValue {}

// ── Provider ──────────────────────────────────────────────────────────

export function WsProvider({ children }: { children: React.ReactNode }) {
  const [alerts, setAlerts] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [lastJobUpdate, setLastJobUpdate] = useState<JobUpdateEvent | null>(null)
  const [lastSubCheck, setLastSubCheck] = useState<SubCheckEvent | null>(null)
  const [lastEvent, setLastEvent] = useState<WsMessage | null>(null)
  const [lastLogEntry, setLastLogEntry] = useState<LogEntry | null>(null)
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
        } else if (msg.type === 'subscription_checked' && msg.sub_id) {
          setLastSubCheck({
            sub_id: msg.sub_id,
            status: msg.status ?? '',
            new_works: msg.new_works ?? 0,
            job_id: msg.job_id ?? null,
          })
        } else if (msg.type === 'log_entry' && msg.log) {
          setLastLogEntry(msg.log as LogEntry)
        } else if (msg.type !== 'ping') {
          // New event types from EventBus — store in lastEvent
          setLastEvent(msg)
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
    <WsConnectionContext value={{ connected }}>
      <WsJobContext value={{ lastJobUpdate, lastSubCheck }}>
        <WsAlertContext value={{ alerts, dismissAlert }}>
          <WsEventContext value={{ lastEvent }}>
            <WsLogContext value={{ lastLogEntry }}>{children}</WsLogContext>
          </WsEventContext>
        </WsAlertContext>
      </WsJobContext>
    </WsConnectionContext>
  )
}

// ── Focused hooks ──────────────────────────────────────────────────────

export function useWsConnection(): WsConnectionContextValue {
  return useContext(WsConnectionContext)
}

export function useWsJobs(): WsJobContextValue {
  return useContext(WsJobContext)
}

export function useWsAlerts(): WsAlertContextValue {
  return useContext(WsAlertContext)
}

export function useWsEvents(): WsEventContextValue {
  return useContext(WsEventContext)
}

export function useWsLogs(): WsLogContextValue {
  return useContext(WsLogContext)
}

// ── Backward-compatible composite hook ────────────────────────────────

export function useWs(): WsContextValue {
  const connection = useContext(WsConnectionContext)
  const jobs = useContext(WsJobContext)
  const alerts = useContext(WsAlertContext)
  const events = useContext(WsEventContext)
  const logs = useContext(WsLogContext)
  return {
    ...connection,
    ...jobs,
    ...alerts,
    ...events,
    ...logs,
  }
}

// Backward-compatible alias
export function useWebSocket(): WsContextValue {
  return useWs()
}
