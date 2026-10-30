'use client'

import useSWR from 'swr'
import { Loader2, ImageIcon } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import Link from 'next/link'
import { AppImage } from '@/components/AppImage'
import { Dialog } from '@/components/ui/dialog'

function toMediaUrl(path: string): string {
  if (path.startsWith('/data/')) return path.replace('/data/', '/media/')
  return path
}

export function SimilarImagesPanel({ imageId, onClose }: { imageId: number; onClose: () => void }) {
  const { data, isLoading, error } = useSWR(['library/images/similar', imageId], () =>
    api.library.findSimilar(imageId),
  )

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      title={t('similar.title')}
      size="xl"
    >
      {isLoading && (
        <div className="flex justify-center py-8">
          <Loader2 className="animate-spin text-vault-text-muted" size={24} />
        </div>
      )}

      {error && (
        <p className="text-sm text-red-400 text-center py-4">
          {error.message || t('common.failedToLoad')}
        </p>
      )}

      {data && data.similar.length === 0 && (
        <div className="text-center py-8">
          <ImageIcon size={32} className="mx-auto text-vault-text-muted mb-2" />
          <p className="text-sm text-vault-text-muted">{t('similar.noResults')}</p>
        </div>
      )}

      {data && data.similar.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
          {data.similar.map((img) => (
            <Link
              key={img.id}
              href={`/library/local/${img.gallery_id}`}
              className="group relative aspect-square rounded-lg overflow-hidden bg-vault-input border border-vault-border hover:border-vault-accent transition-colors"
            >
              <AppImage
                src={toMediaUrl(img.thumb_path || img.file_path)}
                alt={img.filename}
                className="w-full h-full object-cover"
                loading="lazy"
              />
              <span className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-black/70 text-white">
                {t('similar.distance', { d: String(img.distance) })}
              </span>
            </Link>
          ))}
        </div>
      )}
    </Dialog>
  )
}
