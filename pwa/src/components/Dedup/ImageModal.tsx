'use client'
import { useEffect } from 'react'
import { X } from 'lucide-react'
import { t } from '@/lib/i18n'

interface ImageModalProps {
  url: string
  onClose: () => void
}

export function ImageModal({ url, onClose }: ImageModalProps) {
  useEffect(() => {
    const handle = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handle)
    return () => document.removeEventListener('keydown', handle)
  }, [onClose])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('dedup.imagePreview')}
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
      onClick={onClose}
    >
      <button
        className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70"
        onClick={onClose}
        aria-label={t('common.close')}
      >
        <X size={20} />
      </button>
      <img
        src={url}
        alt=""
        className="max-w-full max-h-full object-contain"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  )
}
