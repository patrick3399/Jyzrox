'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { ArrowUp } from 'lucide-react'
import { t } from '@/lib/i18n'

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
