'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { WsMessage } from './types'

export function useWebSocket() {
  const [alerts, setAlerts] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    // Build WS URL: ws://same-host/api/ws
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
        }
      } catch { /* ignore malformed */ }
    }

    ws.onclose = () => {
      setConnected(false)
      // Reconnect after 3s
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
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const dismissAlert = useCallback((index: number) => {
    setAlerts((prev) => prev.filter((_, i) => i !== index))
  }, [])

  return { alerts, connected, dismissAlert }
}
