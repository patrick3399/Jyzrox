'use client'

import { useState, Suspense } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Pencil, Trash2, FolderHeart, Image as ImageIcon, Check, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  useCollections,
  useCreateCollection,
  useUpdateCollection,
  useDeleteCollection,
} from '@/hooks/useCollections'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AppImage } from '@/components/AppImage'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { Collection } from '@/lib/types'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { AlertDialog } from '@/components/ui/alert-dialog'
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
              size="icon"
              onClick={onEditSave}
              aria-label={t('common.save')}
              className="size-8 text-green-400 hover:bg-green-400/10 hover:text-green-400"
            >
              <Check size={15} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={onEditCancel}
              aria-label={t('common.cancel')}
              className="size-8"
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
              size="icon"
              onClick={(e) => {
                e.stopPropagation()
                onEdit(collection)
              }}
              aria-label={t('collections.edit')}
              className="size-8 opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100"
            >
              <Pencil size={15} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(collection.id)
              }}
              aria-label={t('collections.delete')}
              className="size-8 hover:text-red-400 hover:bg-red-400/10 opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100"
            >
              <Trash2 size={15} />
            </Button>
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
      <PageHeader
        spacing="none"
        title={t('collections.title')}
        actions={
          <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
            <Plus size={16} />
            {t('collections.create')}
          </Button>
        }
      />

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
            <Button
              variant="primary"
              size="md"
              onClick={handleCreate}
              disabled={creating || !newName.trim()}
            >
              {creating ? t('common.loading') : t('collections.create')}
            </Button>
            <Button
              variant="secondary"
              size="md"
              onClick={() => {
                setShowCreate(false)
                setNewName('')
                setNewDesc('')
              }}
            >
              {t('common.cancel')}
            </Button>
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
      <AlertDialog
        open={deletingId !== null}
        onOpenChange={(o) => {
          if (!o) setDeletingId(null)
        }}
        title={t('collections.delete')}
        description={t('collections.confirmDelete')}
        confirmLabel={deleting ? t('common.loading') : t('collections.delete')}
        onConfirm={handleDeleteConfirm}
        destructive
        busy={deleting}
      />
    </div>
  )
}

export default function CollectionsPage() {
  return (
    <PageContainer>
      <Suspense
        fallback={
          <div className="flex items-center justify-center min-h-[60vh]">
            <LoadingSpinner size="lg" />
          </div>
        }
      >
        <CollectionsPageInner />
      </Suspense>
    </PageContainer>
  )
}
