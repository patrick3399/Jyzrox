'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { t } from '@/lib/i18n'

interface BackButtonProps {
  fallback: string
}

export function BackButton({ fallback }: BackButtonProps) {
  const router = useRouter()

  useEffect(() => {
    document.documentElement.style.setProperty('--fab-offset', '4.5rem')
    return () => {
      document.documentElement.style.setProperty('--fab-offset', '')
    }
  }, [])

  const handleClick = () => {
    if (window.history.length > 1) {
      router.back()
    } else {
      router.push(fallback)
    }
  }

  return (
    <button
      onClick={handleClick}
      aria-label={t('common.back')}
      className="fixed bottom-[calc(5.5rem+var(--sab))] right-6 z-40
        lg:static lg:bottom-auto lg:right-auto
        w-14 h-14 rounded-full
        bg-vault-card/80 backdrop-blur-sm border border-vault-border
        flex items-center justify-center
        text-vault-text-secondary hover:text-vault-text hover:border-vault-accent/50
        shadow-lg transition-colors active:scale-95
        lg:rounded-lg lg:w-auto lg:h-auto lg:px-3 lg:py-2 lg:shadow-none"
    >
      <ArrowLeft size={24} className="lg:hidden" />
      <ArrowLeft size={16} className="hidden lg:block lg:mr-1.5" />
      <span className="hidden lg:inline text-sm">{t('common.back')}</span>
    </button>
  )
}
