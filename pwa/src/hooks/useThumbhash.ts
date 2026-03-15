'use client'

import { useRef, useEffect, useState, useCallback } from 'react'
import type { WorkerRequest, WorkerResponse, DecodedRGBA } from '@/lib/thumbhash.worker'

// ---------------------------------------------------------------------------
// Module-level shared state — persists across all hook instances in a tab.
// ---------------------------------------------------------------------------

/** Decoded data URLs keyed by base64 thumbhash string. */
const globalCache = new Map<string, string | null>()

/** Pending resolution callbacks keyed by hash, waiting for the worker. */
const pendingCallbacks = new Map<string, Set<() => void>>()

// Single shared worker instance (lazy-initialised on first use).
let sharedWorker: Worker | null = null
let workerFailed = false
let requestCounter = 0

// Callbacks waiting for a specific request id.
const pendingRequests = new Map<number, () => void>()

function getWorker(): Worker | null {
  if (workerFailed) return null
  if (sharedWorker) return sharedWorker

  try {
    sharedWorker = new Worker(
      new URL('../lib/thumbhash.worker.ts', import.meta.url),
      { type: 'module' },
    )

    sharedWorker.onmessage = (e: MessageEvent<WorkerResponse>) => {
      const { id, results } = e.data

      // Paint decoded RGBA onto a tiny canvas to produce a data URL.
      // This is fast because images are at most 32×32 px.
      for (const [hash, decoded] of results) {
        const dataUrl = decoded ? rgbaToDataURL(decoded) : null
        globalCache.set(hash, dataUrl)

        // Notify all hooks waiting for this hash.
        const cbs = pendingCallbacks.get(hash)
        if (cbs) {
          cbs.forEach((cb) => cb())
          pendingCallbacks.delete(hash)
        }
      }

      // Resolve the per-request callback (used to trigger re-renders).
      const reqCb = pendingRequests.get(id)
      if (reqCb) {
        reqCb()
        pendingRequests.delete(id)
      }
    }

    sharedWorker.onerror = () => {
      workerFailed = true
      sharedWorker = null
    }
  } catch {
    workerFailed = true
  }

  return sharedWorker
}

/** Create a data URL from decoded RGBA data on the main thread (sync, cheap for tiny images). */
function rgbaToDataURL(decoded: DecodedRGBA): string | null {
  try {
    const { w, h, rgba } = decoded
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    const imageData = ctx.createImageData(w, h)
    imageData.data.set(rgba)
    ctx.putImageData(imageData, 0, 0)
    return canvas.toDataURL()
  } catch {
    return null
  }
}

/** Synchronous fallback: decode + render on the main thread when the worker is unavailable. */
function decodeSync(hash: string): string | null {
  // Dynamic import is async; for the sync path we inline the canvas approach
  // using the already-imported thumbHashToRGBA via a dynamic require-like call.
  // Because this file is a Client Component module it can import from thumbhash.ts directly.
  // We do it lazily here to avoid loading the module on the server.
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { thumbHashToDataURL } = require('@/lib/thumbhash') as {
      thumbHashToDataURL: (h: string) => string | null
    }
    return thumbHashToDataURL(hash)
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Decode an array of thumbhash base64 strings into data URLs.
 *
 * - Hashes that are already in the global cache are returned immediately.
 * - New hashes are batched and sent to the shared web worker.
 * - Falls back to synchronous decoding if the worker is unavailable.
 * - Results are accumulated reactively: the returned map grows as decoding completes.
 */
export function useThumbhash(hashes: string[]): Map<string, string | null> {
  // Stable reference so we can compare across renders without deep equality.
  const hashesRef = useRef<string[]>([])

  // Snapshot of results we expose to the caller.
  const [snapshot, setSnapshot] = useState<Map<string, string | null>>(() => {
    const map = new Map<string, string | null>()
    for (const hash of hashes) {
      if (globalCache.has(hash)) {
        map.set(hash, globalCache.get(hash) ?? null)
      }
    }
    return map
  })

  const triggerUpdate = useCallback(() => {
    setSnapshot((prev) => {
      const next = new Map(prev)
      let changed = false
      for (const hash of hashesRef.current) {
        if (globalCache.has(hash) && !next.has(hash)) {
          next.set(hash, globalCache.get(hash) ?? null)
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [])

  useEffect(() => {
    hashesRef.current = hashes

    // Determine which hashes still need decoding.
    const uncached = hashes.filter((h) => !globalCache.has(h))

    if (uncached.length === 0) {
      // Everything is cached — just sync the snapshot.
      triggerUpdate()
      return
    }

    const worker = getWorker()

    if (!worker) {
      // Worker unavailable — fall back to synchronous decoding.
      for (const hash of uncached) {
        if (!globalCache.has(hash)) {
          globalCache.set(hash, decodeSync(hash))
        }
      }
      triggerUpdate()
      return
    }

    // Register per-hash callbacks so that if another hook instance already
    // submitted these hashes we avoid a duplicate request.
    const newHashes: string[] = []
    for (const hash of uncached) {
      if (pendingCallbacks.has(hash)) {
        // Already in-flight — just subscribe to the result.
        pendingCallbacks.get(hash)!.add(triggerUpdate)
      } else {
        pendingCallbacks.set(hash, new Set([triggerUpdate]))
        newHashes.push(hash)
      }
    }

    if (newHashes.length === 0) return

    // Send a single batched message for all truly new hashes.
    const id = ++requestCounter
    pendingRequests.set(id, triggerUpdate)
    worker.postMessage({ id, hashes: newHashes } satisfies WorkerRequest)
  }, [hashes, triggerUpdate])

  return snapshot
}
