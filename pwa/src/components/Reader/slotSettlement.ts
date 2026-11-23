'use client'
import { useCallback, useState } from 'react'
import type { ReaderImage } from './types'

/**
 * Whether turning onto this page should wait for it before taking the
 * outgoing page off screen. ReaderImg keeps a paged image invisible until it
 * has loaded and decoded (FE-T34); a video, or a page with no file yet, shows
 * its own placeholder at once.
 */
export function waitsForDecode(image: ReaderImage | null): image is ReaderImage {
  return image != null && image.mediaType === 'image' && image.url != null
}

/**
 * Tracks which mounted PageSlots have settled: their element loaded and
 * decoded, or failed for good. Keyed by page, with the URL it settled for. An
 * entry goes when its slot unmounts, since a remounted slot starts a new
 * element that has to load again.
 */
export function useSlotSettlement() {
  const [settled, setSettled] = useState<ReadonlyMap<number, string | null>>(() => new Map())
  const markSettled = useCallback((pageNum: number, url: string | null) => {
    setSettled((prev) =>
      prev.has(pageNum) && prev.get(pageNum) === url ? prev : new Map(prev).set(pageNum, url),
    )
  }, [])
  const forget = useCallback((pageNum: number) => {
    setSettled((prev) => {
      if (!prev.has(pageNum)) return prev
      const next = new Map(prev)
      next.delete(pageNum)
      return next
    })
  }, [])
  const isSettled = (image: ReaderImage) =>
    settled.has(image.pageNum) && settled.get(image.pageNum) === image.url
  return { isSettled, markSettled, forget }
}
