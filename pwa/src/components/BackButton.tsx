'use client'

import { useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { t } from '@/lib/i18n'
import { consumeTabRestore, getListHref } from '@/lib/navMemory'

interface BackButtonProps {
  fallback: string
}

/** History back that stays inside the section: when this page was reached via
 *  a nav-tab restore of a deep URL, history's previous entry is whatever the
 *  user detoured through (e.g. /trash) — climb to the section's last
 *  list-level URL instead. Otherwise plain history back with a fallback. */
export function smartBack(router: { back: () => void; push: (href: string) => void }, fallback: string): void {
  const sectionRoot = fallback.split('?')[0]
  if (consumeTabRestore(window.location.pathname + window.location.search)) {
    router.push(getListHref(sectionRoot))
    return
  }
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push(fallback)
  }
}

export function BackButton({ fallback }: BackButtonProps) {
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    document.documentElement.style.setProperty('--fab-offset', '4.5rem')
    return () => {
      document.documentElement.style.setProperty('--fab-offset', '')
    }
  }, [])

  const handleClick = () => {
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
