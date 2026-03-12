'use client'

import { useRef, useEffect, useCallback } from 'react'

export function useScrollRestore(key: string, isReady: boolean) {
  const restoredRef = useRef(false)

  useEffect(() => {
    if (!isReady || restoredRef.current) return
    restoredRef.current = true
    const saved = sessionStorage.getItem(key)
    if (!saved) return
    sessionStorage.removeItem(key)
    requestAnimationFrame(() => window.scrollTo(0, Number(saved)))
  }, [isReady, key])

  const saveScroll = useCallback(() => {
    sessionStorage.setItem(key, String(window.scrollY))
  }, [key])

  return { saveScroll }
}
