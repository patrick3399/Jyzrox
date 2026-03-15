'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { createElement } from 'react'
import { RefreshCw } from 'lucide-react'
import { t } from '@/lib/i18n'

const THRESHOLD = 60
const MAX_PULL = 100

interface UsePullToRefreshOptions {
  onRefresh: () => Promise<void> | void
  scrollContainerRef?: React.RefObject<HTMLElement | null>
  enabled?: boolean
}

type PullState = 'idle' | 'pulling' | 'ready' | 'refreshing'

export function usePullToRefresh({
  onRefresh,
  scrollContainerRef,
  enabled = true,
}: UsePullToRefreshOptions) {
  const [pullState, setPullState] = useState<PullState>('idle')
  const [pullDistance, setPullDistance] = useState(0)

  const startYRef = useRef<number>(0)
  const isActiveRef = useRef(false)
  const isRefreshingRef = useRef(false)
  const pullDistanceRef = useRef(0)
  const onRefreshRef = useRef(onRefresh)
  onRefreshRef.current = onRefresh

  const getScrollTop = useCallback((): number => {
    if (scrollContainerRef?.current) {
      return scrollContainerRef.current.scrollTop
    }
    return window.scrollY
  }, [scrollContainerRef])

  const getTarget = useCallback((): Window | HTMLElement => {
    if (scrollContainerRef?.current) {
      return scrollContainerRef.current
    }
    return window
  }, [scrollContainerRef])

  useEffect(() => {
    if (!enabled) return

    const handleTouchStart = (e: TouchEvent) => {
      if (isRefreshingRef.current) return
      if (getScrollTop() > 0) return

      const touch = e.touches[0]
      startYRef.current = touch.clientY
      isActiveRef.current = true
    }

    const handleTouchMove = (e: TouchEvent) => {
      if (!isActiveRef.current || isRefreshingRef.current) return
      if (getScrollTop() > 0) {
        isActiveRef.current = false
        setPullState('idle')
        setPullDistance(0)
        pullDistanceRef.current = 0
        return
      }

      const touch = e.touches[0]
      const deltaY = touch.clientY - startYRef.current

      if (deltaY <= 0) {
        isActiveRef.current = false
        setPullState('idle')
        setPullDistance(0)
        pullDistanceRef.current = 0
        return
      }

      const clamped = Math.min(deltaY * 0.5, MAX_PULL)
      pullDistanceRef.current = clamped
      setPullDistance(clamped)
      setPullState(clamped >= THRESHOLD * 0.5 ? (clamped >= THRESHOLD ? 'ready' : 'pulling') : 'idle')
    }

    const handleTouchEnd = async () => {
      if (!isActiveRef.current || isRefreshingRef.current) return
      isActiveRef.current = false

      if (pullDistanceRef.current >= THRESHOLD) {
        isRefreshingRef.current = true
        setPullState('refreshing')
        setPullDistance(THRESHOLD)
        pullDistanceRef.current = THRESHOLD
        try {
          await onRefreshRef.current()
        } finally {
          isRefreshingRef.current = false
          setPullState('idle')
          setPullDistance(0)
          pullDistanceRef.current = 0
        }
      } else {
        setPullState('idle')
        setPullDistance(0)
        pullDistanceRef.current = 0
      }
    }

    const target = getTarget()

    target.addEventListener('touchstart', handleTouchStart as EventListener, { passive: true })
    target.addEventListener('touchmove', handleTouchMove as EventListener, { passive: true })
    target.addEventListener('touchend', handleTouchEnd as EventListener, { passive: true })

    return () => {
      target.removeEventListener('touchstart', handleTouchStart as EventListener)
      target.removeEventListener('touchmove', handleTouchMove as EventListener)
      target.removeEventListener('touchend', handleTouchEnd as EventListener)
    }
  }, [enabled, getScrollTop, getTarget])

  const isVisible = pullState !== 'idle' || pullDistance > 0
  const progress = Math.min(pullDistance / THRESHOLD, 1)
  const rotation = progress * 360

  const indicator = createElement(
    'div',
    {
      'aria-hidden': true,
      style: {
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        display: 'flex',
        justifyContent: 'center',
        pointerEvents: 'none',
        transform: `translateY(${isVisible ? Math.min(pullDistance, MAX_PULL) - 8 : -48}px)`,
        transition: pullState === 'idle' && !isVisible ? 'transform 0.25s ease' : 'none',
      },
    },
    createElement(
      'div',
      {
        className: [
          'flex items-center gap-2 px-4 py-2 rounded-full shadow-lg text-sm font-medium',
          pullState === 'refreshing' || pullState === 'ready'
            ? 'bg-vault-accent text-white'
            : 'bg-vault-card border border-vault-border text-vault-text-secondary',
        ].join(' '),
      },
      createElement(RefreshCw, {
        size: 16,
        className: pullState === 'refreshing' ? 'animate-spin' : '',
        style:
          pullState === 'refreshing'
            ? undefined
            : { transform: `rotate(${rotation}deg)`, transition: 'none' },
      }),
      createElement(
        'span',
        null,
        pullState === 'refreshing'
          ? t('pullToRefresh.refreshing')
          : pullState === 'ready'
            ? t('pullToRefresh.release')
            : t('pullToRefresh.pull'),
      ),
    ),
  )

  return { indicator, pullState }
}
