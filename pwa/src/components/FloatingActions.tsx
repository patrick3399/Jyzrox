'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { ArrowUp } from 'lucide-react'
import { t } from '@/lib/i18n'

// Grace period for the smooth scroll to run before we snap to the top. Long
// enough that a normal smooth animation completes on its own, short enough that
// a reflow-cancelled scroll is corrected without a visible stall.
const SCROLL_TOP_SETTLE_MS = 450

function getScrollRoot(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[data-scroll-root="true"]')
}

function isIOS() {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  )
}

export function FloatingActions() {
  const pathname = usePathname()
  const [showScrollTop, setShowScrollTop] = useState(false)
  const showRef = useRef(false)

  useEffect(() => {
    const handler = () => {
      const root = getScrollRoot()
      const shouldShow = (root?.scrollTop ?? window.scrollY) > 300
      if (shouldShow !== showRef.current) {
        showRef.current = shouldShow
        setShowScrollTop(shouldShow)
      }
    }
    const root = getScrollRoot()
    window.addEventListener('scroll', handler, { passive: true })
    root?.addEventListener('scroll', handler, { passive: true })
    handler()
    return () => {
      window.removeEventListener('scroll', handler)
      root?.removeEventListener('scroll', handler)
    }
  }, [pathname])

  const handleScrollTop = () => {
    const root = getScrollRoot()
    const behavior: ScrollBehavior = isIOS() ? 'auto' : 'smooth'
    root?.scrollTo({ top: 0, behavior })
    window.scrollTo({ top: 0, behavior })

    if (isIOS()) {
      requestAnimationFrame(() => {
        root?.scrollTo({ top: 0, behavior: 'auto' })
        window.scrollTo({ top: 0, behavior: 'auto' })
      })
    }

    // On a long window-virtualized list (e.g. a large gallery), rows are
    // re-measured as they enter the viewport and reflow the document, which
    // cancels the in-flight smooth scroll before it reaches y=0 — the page
    // stalls partway. Once the animation has had time to run, snap to the top
    // if we are not there yet so the button always lands at 0.
    window.setTimeout(() => {
      const r = getScrollRoot()
      if ((r?.scrollTop ?? window.scrollY) > 0) {
        r?.scrollTo({ top: 0, behavior: 'auto' })
        window.scrollTo({ top: 0, behavior: 'auto' })
      }
    }, SCROLL_TOP_SETTLE_MS)
  }

  if (!showScrollTop) return null

  return (
    <div className="fixed bottom-[calc(5rem+var(--sab)+var(--fab-offset,0rem))] lg:bottom-6 right-4 lg:right-8 z-40 flex flex-col gap-2">
      <button
        onClick={handleScrollTop}
        className="w-12 h-12 rounded-full bg-vault-accent text-white shadow-lg shadow-vault-accent/25 flex items-center justify-center hover:bg-vault-accent/90 transition-all hover:scale-105 active:scale-95"
        aria-label={t('common.scrollToTop')}
      >
        <ArrowUp size={20} />
      </button>
    </div>
  )
}
