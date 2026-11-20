'use client'

import { Pencil, Trash2, FolderHeart, Image as ImageIcon, Check, X } from 'lucide-react'
import { AppImage } from '@/components/AppImage'
import { t } from '@/lib/i18n'
import type { Collection } from '@/lib/types'
import { Button } from '@/components/ui/button'

interface CollectionCardProps {
  collection: Collection
  onEdit: (c: Collection) => void
  onDelete: (id: number) => void
  onClick: (id: number) => void
  editingId: number | null
  editName: string
  onEditNameChange: (v: string) => void
  onEditSave: () => void
  onEditCancel: () => void
}

export function CollectionCard({
  collection,
  onEdit,
  onDelete,
  onClick,
  editingId,
  editName,
  onEditNameChange,
  onEditSave,
  onEditCancel,
}: CollectionCardProps) {
  const isEditing = editingId === collection.id

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden hover:border-vault-accent/50 transition-all group">
      {/* Cover image */}
      <button
        className="w-full aspect-video bg-vault-bg relative overflow-hidden focus:outline-none"
        onClick={() => onClick(collection.id)}
        aria-label={collection.name}
      >
        {collection.cover_thumb ? (
          <AppImage
            src={collection.cover_thumb}
            alt={collection.name}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <FolderHeart size={48} className="text-vault-text-secondary/30" />
          </div>
        )}
        {/* Gallery count badge */}
        <span className="absolute bottom-2 right-2 flex items-center gap-1 px-2 py-0.5 rounded bg-black/60 text-white text-xs">
          <ImageIcon size={12} aria-hidden="true" />
          {collection.gallery_count}
        </span>
      </button>

      {/* Footer */}
      <div className="p-3 flex items-center gap-2">
        {isEditing ? (
          <>
            <input
              autoFocus
              value={editName}
              onChange={(e) => onEditNameChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onEditSave()
                if (e.key === 'Escape') onEditCancel()
              }}
              className="flex-1 min-w-0 px-2 py-1 bg-vault-input border border-vault-accent rounded text-sm text-vault-text focus:outline-none"
              placeholder={t('collections.namePlaceholder')}
            />
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onEditSave}
              aria-label={t('common.save')}
              className="text-green-400 hover:bg-green-400/10 hover:text-green-400"
            >
              <Check size={15} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onEditCancel}
              aria-label={t('common.cancel')}
            >
              <X size={15} />
            </Button>
          </>
        ) : (
          <>
            <button
              className="flex-1 min-w-0 text-left focus:outline-none"
              onClick={() => onClick(collection.id)}
            >
              <p className="font-medium text-sm text-vault-text truncate">{collection.name}</p>
              <p className="text-xs text-vault-text-secondary mt-0.5">
                {t('collections.galleryCount', { count: String(collection.gallery_count) })}
              </p>
            </button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={(e) => {
                e.stopPropagation()
                onEdit(collection)
              }}
              aria-label={t('collections.edit')}
              className="opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100"
            >
              <Pencil size={15} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(collection.id)
              }}
              aria-label={t('collections.delete')}
              className="hover:text-red-400 hover:bg-red-400/10 opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100"
            >
              <Trash2 size={15} />
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
