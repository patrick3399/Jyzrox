/**
 * Web Worker for thumbhash decoding.
 * Runs the expensive DCT math off the main thread.
 *
 * Receives: { id: number; hashes: string[] }
 * Responds: { id: number; results: Array<[string, { w: number; h: number; rgba: number[] } | null]> }
 */

import { thumbHashToRGBA } from './thumbhash'

export interface WorkerRequest {
  id: number
  hashes: string[]
}

export interface DecodedRGBA {
  w: number
  h: number
  rgba: number[]
}

export interface WorkerResponse {
  id: number
  results: Array<[string, DecodedRGBA | null]>
}

self.onmessage = (e: MessageEvent<WorkerRequest>) => {
  const { id, hashes } = e.data
  const results: WorkerResponse['results'] = []

  for (const hash of hashes) {
    try {
      const { w, h, rgba } = thumbHashToRGBA(hash)
      // Transfer rgba as a plain number[] so it survives structured clone without
      // needing a Transferable — the arrays are tiny (max 32×32×4 = 4096 bytes).
      results.push([hash, { w, h, rgba: Array.from(rgba) }])
    } catch {
      results.push([hash, null])
    }
  }

  self.postMessage({ id, results } satisfies WorkerResponse)
}
