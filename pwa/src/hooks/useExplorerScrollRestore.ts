'use client'

import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

import { loadScroll, registerScrollSaver, saveScroll } from './explorerHistory'

/** Saves a scroll container's position per list URL and puts it back when
 *  that URL is shown again with its data rendered.
 *
 *  The capture callback sits in a ref (updated in a layout effect) so the
 *  listener effects never depend on it: re-subscribing on every append would
 *  cancel a pending frame and lose the position (FE-T19). */
export function useExplorerScrollRestore(
  containerRef: RefObject<HTMLElement | null>,
  urlKey: string,
  ready: boolean,
): void {
  const urlKeyRef = useRef(urlKey)
  const readyRef = useRef(ready)
  const captureRef = useRef<() => void>(() => {})
  const restoredForRef = useRef<string | null>(null)
  const hasRestoredRef = useRef(false)

  useLayoutEffect(() => {
    urlKeyRef.current = urlKey
    readyRef.current = ready
    captureRef.current = () => {
      const element = containerRef.current
      if (element && readyRef.current) saveScroll(urlKeyRef.current, element.scrollTop)
    }
  })

  useEffect(() => registerScrollSaver(() => captureRef.current()), [])

  useEffect(() => {
    const onPageHide = () => captureRef.current()
    window.addEventListener('pagehide', onPageHide)
    return () => window.removeEventListener('pagehide', onPageHide)
  }, [])

  useEffect(() => {
    const element = containerRef.current
    if (!ready || !element) return
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        captureRef.current()
      })
    }
    element.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      element.removeEventListener('scroll', onScroll)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [ready, containerRef])

  useEffect(() => {
    if (!ready) {
      restoredForRef.current = null
      return
    }
    const element = containerRef.current
    if (!element || restoredForRef.current === urlKey) return
    restoredForRef.current = urlKey
    const saved = loadScroll(urlKey)
    if (saved !== null) element.scrollTop = saved
    else if (hasRestoredRef.current) element.scrollTop = 0
    hasRestoredRef.current = true
  }, [urlKey, ready, containerRef])
}
