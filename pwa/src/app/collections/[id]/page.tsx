'use client'

import { useState, useRef, Suspense } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { X, Pencil, FolderHeart } from 'lucide-react'
import { toast } from 'sonner'
import { useCollection, useUpdateCollection, useRemoveGalleryFromCollection } from '@/hooks/useCollections'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { Pagination } from '@/components/Pagination'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'

const PAGE_LIMIT = 24

function CollectionDetailInner() {
  useLocale()
  const params = useParams()
  const id = Number(params.id)

  const [page, setPage] = useState(0)
  const { data, isLoading, isValidating, mutate } = useCollection(id, { page, limit: PAGE_LIMIT })
  const { trigger: update } = useUpdateCollection()
  const { trigger: removeGallery } = useRemoveGalleryFromCollection()

  // Inline name editing
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const nameInputRef = useRef<HTMLInputElement>(null)

  // Inline description editing
  const [editingDesc, setEditingDesc] = useState(false)
  const [descInput, setDescInput] = useState('')

  const handleStartEditName = () => {
    setNameInput(data?.name ?? '')
    setEditingName(true)
    // Focus happens via autoFocus on the input
  }

  const handleSaveName = async () => {
    const name = nameInput.trim()
    setEditingName(false)
    if (!name || name === data?.name) return
    try {
      await update({ id, data: { name } })
      await mutate()
      toast.success(t('collections.updated'))
    } catch {
      toast.error(t('common.error'))
    }
  }

  const handleSaveDesc = async () => {
    const description = descInput.trim()
    setEditingDesc(false)
    if (description === (data?.description ?? '')) return
    try {
      await update({ id, data: { description: description || undefined } })
      await mutate()
      toast.success(t('collections.updated'))
    } catch {
      toast.error(t('common.error'))
    }
  }

  const handleRemove = async (galleryId: number) => {
    try {
      await removeGallery({ collectionId: id, galleryId })
      await mutate()
      toast.success(t('collections.galleryRemoved'))
    } catch {
      toast.error(t('common.error'))
    }
  }

  const galleries = data?.galleries ?? []
  // The API returns gallery_count as the total across all pages
  const total = data?.gallery_count ?? 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <BackButton fallback="/collections" />

        <div className="flex-1 min-w-0 space-y-1">
          {/* Editable name */}
          {editingName ? (
            <input
              ref={nameInputRef}
              autoFocus
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onBlur={handleSaveName}
              onKeyDown={(e) => {
                if (e.key === 'Enter') nameInputRef.current?.blur()
                if (e.key === 'Escape') {
                  setEditingName(false)
                }
              }}
              className="w-full max-w-lg px-2 py-1 bg-vault-input border border-vault-accent rounded-lg text-2xl font-bold text-vault-text focus:outline-none"
            />
          ) : (
            <div className="flex items-center gap-2 group/title">
              {isLoading ? (
                <div className="h-8 w-48 bg-vault-border/40 rounded animate-pulse" />
              ) : (
                <>
                  <h1
                    className="text-2xl font-bold text-vault-text cursor-pointer hover:text-indigo-400 transition-colors truncate"
                    onClick={handleStartEditName}
                    title={t('collections.edit')}
                  >
                    {data?.name ?? '…'}
                  </h1>
                  <button
                    onClick={handleStartEditName}
                    aria-label={t('collections.edit')}
                    className="p-1 rounded text-vault-text-secondary hover:text-vault-text opacity-0 group-hover/title:opacity-100 transition-all"
                  >
                    <Pencil size={14} />
                  </button>
                </>
              )}
            </div>
          )}

          {/* Editable description */}
          {editingDesc ? (
            <input
              autoFocus
              value={descInput}
              onChange={(e) => setDescInput(e.target.value)}
              onBlur={handleSaveDesc}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveDesc()
                if (e.key === 'Escape') setEditingDesc(false)
              }}
              placeholder={t('collections.descriptionPlaceholder')}
              className="w-full max-w-lg px-2 py-1 bg-vault-input border border-vault-accent rounded-lg text-sm text-vault-text focus:outline-none"
            />
          ) : (
            <p
              className="text-sm text-vault-text-secondary cursor-pointer hover:text-vault-text transition-colors"
              onClick={() => {
                setDescInput(data?.description ?? '')
                setEditingDesc(true)
              }}
              title={t('collections.description')}
            >
              {data?.description || (
                <span className="italic opacity-50">{t('collections.descriptionPlaceholder')}</span>
              )}
            </p>
          )}

          {/* Count */}
          {!isLoading && (
            <p className="text-xs text-vault-text-secondary">
              {t('collections.galleryCount', { count: String(total) })}
            </p>
          )}
        </div>
      </div>

      {/* Gallery grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      ) : !galleries.length ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-vault-text-secondary">
          <FolderHeart size={48} className="opacity-30" />
          <p>{t('collections.empty')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
          {galleries.map((g) => (
            <div key={g.id} className="group relative">
              <Link
                href={`/library/${g.source}/${g.source_id}`}
                className="block bg-vault-card border border-vault-border rounded-lg overflow-hidden hover:border-vault-accent/50 transition-all"
              >
                <div className="aspect-[3/4] bg-vault-bg overflow-hidden">
                  {g.cover_thumb ? (
                    <img
                      src={g.cover_thumb}
                      alt={g.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      loading="lazy"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-vault-text-secondary/20">
                      <FolderHeart size={32} />
                    </div>
                  )}
                </div>
                <div className="p-2">
                  <p className="text-xs text-vault-text truncate">{g.title}</p>
                </div>
              </Link>

              {/* Remove button overlay */}
              <button
                onClick={() => handleRemove(g.id)}
                aria-label={t('collections.removeGallery')}
                className="absolute top-1.5 right-1.5 z-10 p-1 rounded bg-red-600/80 hover:bg-red-600 text-white opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Pagination — use total from gallery_count */}
      {total > PAGE_LIMIT && (
        <Pagination
          page={page}
          total={total}
          pageSize={PAGE_LIMIT}
          onChange={(p) => setPage(p)}
          isLoading={isValidating}
        />
      )}
    </div>
  )
}

export default function CollectionDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[60vh]">
          <LoadingSpinner size="lg" />
        </div>
      }
    >
      <CollectionDetailInner />
    </Suspense>
  )
}
