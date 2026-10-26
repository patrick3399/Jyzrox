'use client'

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, FolderHeart, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useCollections, revalidateCollections } from '@/hooks/useCollections'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'

interface AddToCollectionMenuProps {
  /**
   * Single-gallery mode: shows a check mark on collections that already
   * contain the gallery and toggles membership (add / remove) per row.
   */
  galleryId?: number
  /**
   * Multi-gallery mode (library select bar): no check marks, a row click adds
   * every gallery through the batch endpoint and closes the menu.
   */
  galleryIds?: number[]
  /** Called after galleries were added (e.g. to refresh the list / leave select mode). */
  onChanged?: () => void | Promise<void>
  /** Trigger button class. */
  className?: string
  /** Trigger button content; defaults to icon + "Add to Collection". */
  children?: ReactNode
  /** Accessible name for an icon-only trigger. */
  ariaLabel?: string
  disabled?: boolean
  /** Told when the sheet opens or closes, e.g. so page-level shortcuts pause. */
  onOpenChange?: (open: boolean) => void
}

/**
 * Trigger button + modal sheet (bottom sheet on small screens, centered dialog
 * from `sm`) listing collections with an inline "new collection" input.
 * Rendered in a portal so it is not clipped by fixed bars / overflow parents.
 */
export function AddToCollectionMenu({
  galleryId,
  galleryIds,
  onChanged,
  className,
  children,
  ariaLabel,
  disabled,
  onOpenChange,
}: AddToCollectionMenuProps) {
  const singleMode = galleryId !== undefined
  const [open, setOpenState] = useState(false)
  const [newName, setNewName] = useState('')
  const [busyId, setBusyId] = useState<number | 'new' | null>(null)

  const { data, isLoading } = useCollections(open, galleryId)
  const collections = data?.collections ?? []

  const setOpen = useCallback(
    (next: boolean) => {
      setOpenState(next)
      onOpenChange?.(next)
    },
    [onOpenChange],
  )

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // This Escape dismisses the sheet and nothing else. Detail pages listen
      // on window for the same key to go back; document listeners run first.
      e.preventDefault()
      e.stopPropagation()
      setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, setOpen])

  const close = () => {
    setOpen(false)
    setNewName('')
  }

  const warnDenied = (denied: number[] | undefined) => {
    if (denied && denied.length > 0) {
      toast.warning(t('collections.addDenied', { count: String(denied.length) }))
    }
  }

  /** Add the target gallery/galleries to one collection. Returns false on failure. */
  const addTo = async (collectionId: number, collectionName: string): Promise<boolean> => {
    try {
      if (singleMode) {
        const res = await api.collections.addGalleries(collectionId, [galleryId])
        warnDenied(res.denied)
        if (res.added > 0) {
          toast.success(t('collections.galleryAddedTo', { name: collectionName }))
        }
      } else {
        const ids = galleryIds ?? []
        const res = await api.library.batchGalleries({
          action: 'add_to_collection',
          gallery_ids: ids,
          collection_id: collectionId,
        })
        warnDenied(res.denied)
        toast.success(t('collections.addedToCollection', { count: String(res.affected) }))
      }
      return true
    } catch {
      toast.error(t('collections.addFailed'))
      return false
    }
  }

  const afterAdd = async () => {
    await revalidateCollections()
    await onChanged?.()
  }

  const handleRowClick = async (id: number, name: string, contains: boolean) => {
    if (busyId !== null) return
    setBusyId(id)
    try {
      if (singleMode && contains) {
        try {
          await api.collections.removeGallery(id, galleryId)
          toast.success(t('collections.galleryRemoved'))
        } catch {
          toast.error(t('collections.removeFailed'))
          return
        }
        await revalidateCollections()
        return
      }
      const ok = await addTo(id, name)
      if (!ok) return
      await afterAdd()
      if (!singleMode) close()
    } finally {
      setBusyId(null)
    }
  }

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name || busyId !== null) return
    setBusyId('new')
    try {
      let created: { id: number; name: string }
      try {
        created = await api.collections.create({ name })
      } catch {
        toast.error(t('collections.createFailed'))
        return
      }
      // The collection exists now even if adding fails, so always refresh lists.
      const ok = await addTo(created.id, created.name)
      if (ok) {
        await afterAdd()
      } else {
        await revalidateCollections()
      }
      setNewName('')
      if (!singleMode && ok) close()
    } finally {
      setBusyId(null)
    }
  }

  const sheet = open && typeof document !== 'undefined' && (
    <div
      className="fixed inset-0 z-[70] flex items-end sm:items-center justify-center bg-black/50"
      onClick={close}
    >
      <div
        role="dialog"
        aria-label={t('collections.addToCollection')}
        className="w-full sm:w-96 sm:max-w-[90vw] max-h-[80vh] flex flex-col bg-vault-card border border-vault-border rounded-t-xl sm:rounded-lg pb-[var(--sab)] sm:pb-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-vault-border">
          <h3 className="text-base font-medium text-vault-text">
            {t('collections.addToCollection')}
          </h3>
          <button
            type="button"
            onClick={close}
            aria-label={t('common.close')}
            className="p-2 -m-2 text-vault-text-muted hover:text-vault-text"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
          {isLoading ? (
            <div className="flex justify-center py-6">
              <LoadingSpinner size="md" />
            </div>
          ) : collections.length === 0 ? (
            <p className="px-4 py-4 text-sm text-vault-text-muted">
              {t('collections.noCollections')}
            </p>
          ) : (
            <ul>
              {collections.map((c) => {
                const contains = singleMode && c.contains_gallery === true
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => handleRowClick(c.id, c.name, contains)}
                      disabled={busyId !== null}
                      aria-pressed={singleMode ? contains : undefined}
                      className="w-full flex items-center gap-3 px-4 py-3 min-h-11 text-left text-sm text-vault-text hover:bg-vault-hover active:bg-vault-hover transition-colors disabled:opacity-60 border-b border-vault-border/50 last:border-b-0"
                    >
                      <span className="w-4 shrink-0 flex justify-center">
                        {busyId === c.id ? (
                          <LoadingSpinner size="sm" />
                        ) : contains ? (
                          <Check
                            size={16}
                            className="text-vault-accent"
                            aria-label={t('collections.inCollection')}
                          />
                        ) : null}
                      </span>
                      <span className="flex-1 min-w-0 truncate">{c.name}</span>
                      <span className="text-xs text-vault-text-muted shrink-0">
                        {c.gallery_count}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <form
          className="flex items-center gap-2 px-4 py-3 border-t border-vault-border"
          onSubmit={(e) => {
            e.preventDefault()
            void handleCreate()
          }}
        >
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t('collections.newCollection')}
            aria-label={t('collections.newCollection')}
            maxLength={200}
            className="flex-1 min-w-0 bg-vault-input border border-vault-border rounded px-3 py-2 text-base sm:text-sm text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover"
          />
          <button
            type="submit"
            disabled={!newName.trim() || busyId !== null}
            className="shrink-0 flex items-center gap-1.5 px-3 py-2 bg-vault-accent hover:bg-vault-accent/80 rounded text-white text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {busyId === 'new' ? <LoadingSpinner size="sm" /> : <Plus size={14} />}
            {t('collections.createAndAdd')}
          </button>
        </form>
      </div>
    </div>
  )

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        aria-label={ariaLabel}
        title={ariaLabel}
        className={className}
      >
        {children ?? (
          <>
            <FolderHeart size={14} />
            {t('collections.addToCollection')}
          </>
        )}
      </button>
      {sheet ? createPortal(sheet, document.body) : null}
    </>
  )
}
