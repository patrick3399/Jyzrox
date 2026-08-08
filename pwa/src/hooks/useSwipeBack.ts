'use client'

import { useEffect, useRef } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { smartBack } from '@/lib/navBack'

const EDGE_THRESHOLD = 24
const MIN_SWIPE = 60
const DIR_RATIO = 1.5

function getFallback(pathname: string): string {
  if (pathname.startsWith('/e-hentai/')) return '/e-hentai'
  if (pathname.startsWith('/library/')) return '/library'
  if (pathname.startsWith('/artists/')) return '/artists'
  if (pathname.startsWith('/pixiv/illust/')) return '/pixiv'
  return '/'
}

interface UseSwipeBackOptions {
  enabled?: boolean
}

function isStandaloneApp(): boolean {
  if (typeof window === 'undefined') return false
  const nav = window.navigator as Navigator & { standalone?: boolean }
  return window.matchMedia('(display-mode: standalone)').matches || nav.standalone === true
}

export function useSwipeBack({ enabled = true }: UseSwipeBackOptions = {}) {
  const router = useRouter()
  const pathname = usePathname()
  const startXRef = useRef<number>(0)
  const startYRef = useRef<number>(0)

  useEffect(() => {
    if (!enabled || !isStandaloneApp()) return

    const handleTouchStart = (e: TouchEvent) => {
      const touch = e.touches[0]
      startXRef.current = touch.clientX
      startYRef.current = touch.clientY
    }

    const handleTouchEnd = (e: TouchEvent) => {
      if (startXRef.current >= EDGE_THRESHOLD) return

      const touch = e.changedTouches[0]
      const deltaX = touch.clientX - startXRef.current
      const deltaY = touch.clientY - startYRef.current

      if (deltaX >= MIN_SWIPE && deltaX / Math.abs(deltaY) > DIR_RATIO) {
        // Must resolve the destination exactly like the back FAB: in a
        // standalone app this gesture is the only back affordance, and a page
        // reached by a nav-tab restore has an unrelated section as its previous
        // history entry.
        smartBack(router, getFallback(pathname))
      }
    }

    document.addEventListener('touchstart', handleTouchStart, { passive: true })
    document.addEventListener('touchend', handleTouchEnd, { passive: true })

    return () => {
      document.removeEventListener('touchstart', handleTouchStart)
      document.removeEventListener('touchend', handleTouchEnd)
    }
  }, [enabled, pathname, router])
}
