'use client'

import { useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { t } from '@/lib/i18n'
import { smartBack } from '@/lib/navBack'

interface BackButtonProps {
  fallback: string
  /** Always navigate to `fallback` (the structural parent) instead of walking
   *  browser history. Use for nested hierarchies where "back" should climb one
   *  level up the tree, not return to whatever page was visited previously
   *  (e.g. a chapter reached from search should go up to its chapter list). */
  toParent?: boolean
}

export function BackButton({ fallback, toParent = false }: BackButtonProps) {
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    document.documentElement.style.setProperty('--fab-offset', '4.5rem')
    return () => {
      document.documentElement.style.setProperty('--fab-offset', '')
    }
  }, [])

  const handleClick = () => {
    if (toParent) {
      router.push(fallback)
      return
    }
    if (fallback === '/settings' && pathname?.startsWith('/settings/')) {
      router.push(fallback)
      return
    }
    smartBack(router, fallback)
  }

  return (
    <button
      onClick={handleClick}
      aria-label={t('common.back')}
      className="fixed bottom-[calc(5.5rem+var(--sab))] right-6 z-40
        w-14 h-14 rounded-full
        bg-vault-card/80 backdrop-blur-sm border border-vault-border
        flex items-center justify-center
        text-vault-text-secondary hover:text-vault-text hover:border-vault-accent/50
        shadow-lg transition-colors active:scale-95"
    >
      <ArrowLeft size={24} />
    </button>
  )
}
