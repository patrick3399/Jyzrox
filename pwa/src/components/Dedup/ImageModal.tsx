'use client'
import { useState } from 'react'
import { Dialog } from '@base-ui/react/dialog'
import { Minus, Plus, RotateCcw, X } from 'lucide-react'
import { t } from '@/lib/i18n'
import { overlayOpenChange } from '@/components/ui/overlay'

interface ImageModalProps {
  url: string
  onClose: () => void
}

export function ImageModal({ url, onClose }: ImageModalProps) {
  const [scale, setScale] = useState(1)
  return (
    <Dialog.Root
      open
      onOpenChange={overlayOpenChange((next) => {
        if (!next) onClose()
      })}
    >
      <Dialog.Portal>
        <Dialog.Popup
          aria-label={t('dedup.imagePreview')}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/90 outline-none transition-opacity duration-(--motion-base) ease-vault-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0"
          onClick={onClose}
        >
          <button
            className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70"
            onClick={onClose}
            aria-label={t('common.close')}
          >
            <X size={20} />
          </button>
          <div className="absolute left-4 top-4 z-10 flex items-center gap-1 rounded-full bg-black/60 p-1 text-white">
            <button
              className="p-2"
              onClick={(e) => {
                e.stopPropagation()
                setScale((value) => Math.max(0.25, value - 0.25))
              }}
              aria-label={t('dedup.zoomOut')}
            >
              <Minus size={18} />
            </button>
            <span className="w-12 text-center text-xs">{Math.round(scale * 100)}%</span>
            <button
              className="p-2"
              onClick={(e) => {
                e.stopPropagation()
                setScale((value) => Math.min(4, value + 0.25))
              }}
              aria-label={t('dedup.zoomIn')}
            >
              <Plus size={18} />
            </button>
            <button
              className="p-2"
              onClick={(e) => {
                e.stopPropagation()
                setScale(1)
              }}
              aria-label={t('dedup.zoomReset')}
            >
              <RotateCcw size={18} />
            </button>
          </div>
          <div className="h-full w-full overflow-auto p-8" onClick={(e) => e.stopPropagation()}>
            <div className="flex min-h-full min-w-full items-center justify-center">
              <img
                src={url}
                alt=""
                style={{ transform: `scale(${scale})`, transformOrigin: 'center' }}
                className="max-w-full max-h-[calc(100vh-4rem)] object-contain transition-transform"
              />
            </div>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
