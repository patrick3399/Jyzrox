'use client'

import { useState, Suspense } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Pencil, Trash2, FolderHeart, Image as ImageIcon, Check, X } from 'lucide-react'
import { toast } from 'sonner'
import { useCollections, useCreateCollection, useUpdateCollection, useDeleteCollection } from '@/hooks/useCollections'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { Collection } from '@/lib/types'

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

function CollectionCard({
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
          <img
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
            <button
              onClick={onEditSave}
              aria-label={t('common.save')}
              className="p-1.5 rounded text-green-400 hover:bg-green-400/10 transition-colors"
            >
              <Check size={15} />
            </button>
            <button
              onClick={onEditCancel}
              aria-label={t('common.cancel')}
              className="p-1.5 rounded text-vault-text-secondary hover:bg-vault-border/40 transition-colors"
            >
              <X size={15} />
            </button>
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
            <button
              onClick={(e) => {
                e.stopPropagation()
                onEdit(collection)
              }}
              aria-label={t('collections.edit')}
              className="p-1.5 rounded text-vault-text-secondary hover:text-vault-text hover:bg-vault-border/40 opacity-0 group-hover:opacity-100 transition-all"
            >
              <Pencil size={15} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete(collection.id)
              }}
              aria-label={t('collections.delete')}
              className="p-1.5 rounded text-vault-text-secondary hover:text-red-400 hover:bg-red-400/10 opacity-0 group-hover:opacity-100 transition-all"
            >
              <Trash2 size={15} />
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function CollectionsPageInner() {
  useLocale()
  const router = useRouter()
  const { data, isLoading, mutate } = useCollections()
  const { trigger: create } = useCreateCollection()
  const { trigger: update } = useUpdateCollection()
  const { trigger: del } = useDeleteCollection()

  // Create form state
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [creating, setCreating] = useState(false)

  // Inline edit state
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')

  // Delete confirm state
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    try {
      await create({ name, description: newDesc.trim() || undefined })
      await mutate()
      toast.success(t('collections.created'))
      setNewName('')
      setNewDesc('')
      setShowCreate(false)
    } catch {
      toast.error(t('common.error'))
    } finally {
      setCreating(false)
    }
  }

  const handleEditStart = (c: Collection) => {
    setEditingId(c.id)
    setEditName(c.name)
  }

  const handleEditSave = async () => {
    if (editingId === null) return
    const name = editName.trim()
    if (!name) {
      setEditingId(null)
      return
    }
    try {
      await update({ id: editingId, data: { name } })
      await mutate()
      toast.success(t('collections.updated'))
    } catch {
      toast.error(t('common.error'))
    } finally {
      setEditingId(null)
    }
  }

  const handleEditCancel = () => {
    setEditingId(null)
  }

  const handleDeleteConfirm = async () => {
    if (deletingId === null) return
    setDeleting(true)
    try {
      await del(deletingId)
      await mutate()
      toast.success(t('collections.deleted'))
    } catch {
      toast.error(t('common.error'))
    } finally {
      setDeletingId(null)
      setDeleting(false)
    }
  }

  const collections = data?.collections ?? []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold text-vault-text">{t('collections.title')}</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus size={16} />
          {t('collections.create')}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-vault-card border border-vault-border rounded-xl p-4 space-y-3">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            placeholder={t('collections.namePlaceholder')}
            className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder:text-vault-text-secondary focus:outline-none focus:ring-1 focus:ring-vault-accent"
          />
          <input
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder={t('collections.descriptionPlaceholder')}
            className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder:text-vault-text-secondary focus:outline-none focus:ring-1 focus:ring-vault-accent"
          />
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={creating || !newName.trim()}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
            >
              {creating ? t('common.loading') : t('collections.create')}
            </button>
            <button
              onClick={() => {
                setShowCreate(false)
                setNewName('')
                setNewDesc('')
              }}
              className="px-4 py-2 bg-vault-card border border-vault-border hover:border-vault-accent/50 text-vault-text-secondary text-sm rounded-lg transition-colors"
            >
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}

      {/* Collection grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      ) : !collections.length ? (
        <div className="text-center py-12 text-vault-text-secondary">
          {t('collections.noCollections')}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {collections.map((c) => (
            <CollectionCard
              key={c.id}
              collection={c}
              onEdit={handleEditStart}
              onDelete={(id) => setDeletingId(id)}
              onClick={(id) => router.push(`/collections/${id}`)}
              editingId={editingId}
              editName={editName}
              onEditNameChange={setEditName}
              onEditSave={handleEditSave}
              onEditCancel={handleEditCancel}
            />
          ))}
        </div>
      )}

      {/* Delete confirm dialog */}
      {deletingId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-vault-card border border-vault-border rounded-xl p-6 max-w-sm w-full space-y-4">
            <p className="text-vault-text text-sm">{t('collections.confirmDelete')}</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeletingId(null)}
                disabled={deleting}
                className="px-4 py-2 bg-vault-card border border-vault-border hover:border-vault-accent/50 text-vault-text-secondary text-sm rounded-lg transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleDeleteConfirm}
                disabled={deleting}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {deleting ? t('common.loading') : t('collections.delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function CollectionsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[60vh]">
          <LoadingSpinner size="lg" />
        </div>
      }
    >
      <CollectionsPageInner />
    </Suspense>
  )
}
