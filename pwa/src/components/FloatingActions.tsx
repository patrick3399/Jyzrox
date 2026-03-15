'use client'

import { useState, useEffect } from 'react'
import { ArrowUp } from 'lucide-react'
import { t } from '@/lib/i18n'

export function FloatingActions() {
  const [showScrollTop, setShowScrollTop] = useState(false)

  useEffect(() => {
    const handler = () => {
      setShowScrollTop(window.scrollY > 300)
    }
    window.addEventListener('scroll', handler, { passive: true })
    return () => window.removeEventListener('scroll', handler)
  }, [])

  if (!showScrollTop) return null

  return (
    <div className="fixed bottom-[calc(5rem+var(--sab)+var(--fab-offset,0rem))] lg:bottom-6 right-4 lg:right-8 z-40 flex flex-col gap-2">
      <button
        onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        className="w-12 h-12 rounded-full bg-vault-accent text-white shadow-lg shadow-vault-accent/25 flex items-center justify-center hover:bg-vault-accent/90 transition-all hover:scale-105 active:scale-95"
        aria-label={t('common.scrollToTop')}
      >
        <ArrowUp size={20} />
      </button>
    </div>
  )
}
