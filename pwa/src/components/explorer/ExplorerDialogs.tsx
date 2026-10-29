'use client'

import { useEffect, useMemo, useState } from 'react'
import useSWR from 'swr'
import { Loader2, X } from 'lucide-react'
import { toast } from 'sonner'

import { useCategoryRegistry } from '@/hooks/useCategoryRegistry'
import { api } from '@/lib/api'
import type { ExplorerGalleryItem } from '@/lib/api'
import { t } from '@/lib/i18n'

import { galleryName, type QuerySelection } from './shared'

export function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4" onMouseDown={onClose}>
      <section role="dialog" aria-modal="true" aria-label={title} className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-t-xl border border-vault-border bg-vault-card shadow-2xl sm:rounded-xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="sticky top-0 flex items-center justify-between border-b border-vault-border bg-vault-card px-5 py-4">
          <h2 className="font-semibold text-vault-text">{title}</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-vault-text-muted hover:bg-vault-card-hover"><X size={18} /></button>
        </header>
        {children}
      </section>
    </div>
  )
}

const METADATA_FIELDS = ['title', 'title_jpn', 'category', 'language', 'artist_id', 'uploader', 'visibility'] as const

export function MetadataDialog({
  selection,
  querySelection,
  onClose,
  onDone,
}: {
  selection: ExplorerGalleryItem[]
  querySelection: QuerySelection | null
  onClose: () => void
  onDone: () => void
}) {
  const [modes, setModes] = useState<Record<string, 'keep' | 'set' | 'clear'>>({})
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const { data: categoryRegistry } = useCategoryRegistry()
  const categoryNames = useMemo(
    () => [...(categoryRegistry?.categories ?? [])].sort((a, b) => a.sort_order - b.sort_order).map((item) => item.name),
    [categoryRegistry],
  )
  const commonValues = useMemo(
    () => Object.fromEntries(
      METADATA_FIELDS.map((field) => [
        field,
        selection.length > 0 && selection.every((item) => String(item[field] ?? '') === String(selection[0][field] ?? ''))
          ? String(selection[0][field] ?? '')
          : '',
      ]),
    ),
    [selection],
  )

  const categoryMixed = selection.length > 0 && !selection.every((item) => (item.category ?? '') === (selection[0].category ?? ''))
  const categoryValue = values.category ?? (categoryNames.includes(commonValues.category) ? commonValues.category : '')
  const categoryInvalid = (modes.category || 'keep') === 'set' && !categoryNames.includes(categoryValue)

  const submit = async () => {
    if (categoryInvalid) return
    const fields: Record<string, { mode: 'set' | 'clear'; value?: string }> = {}
    for (const field of METADATA_FIELDS) {
      const mode = modes[field] || 'keep'
      if (mode === 'set') fields[field] = { mode, value: field === 'category' ? categoryValue : values[field] ?? commonValues[field] }
      if (mode === 'clear') fields[field] = { mode }
    }
    if (Object.keys(fields).length === 0) return
    setSaving(true)
    try {
      await api.explorer.bulkMetadata({
        ...(querySelection
          ? { selection_token: querySelection.token, excluded_ids: [...querySelection.excluded] }
          : { gallery_ids: selection.map((item) => item.id) }),
        fields,
        lock_fields: true,
      })
      toast.success(t('explorer.metadataUpdated'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={t('explorer.editMetadata')} onClose={onClose}>
      <div className="space-y-4 p-5">
        <p className="text-sm text-vault-text-muted">{t('explorer.manualFieldsLocked')}</p>
        {METADATA_FIELDS.map((field) => {
          const common = commonValues[field]
          return (
            <div key={field} className="grid grid-cols-[110px_minmax(0,1fr)] gap-3">
              <select
                aria-label={`${field} mode`}
                value={modes[field] || 'keep'}
                onChange={(event) => setModes((current) => ({ ...current, [field]: event.target.value as 'keep' | 'set' | 'clear' }))}
                className="rounded-md border border-vault-border bg-vault-bg px-2 py-2 text-sm text-vault-text"
              >
                <option value="keep">{t('explorer.keep')}</option>
                <option value="set">{t('explorer.set')}</option>
                {field !== 'visibility' && <option value="clear">{t('explorer.clear')}</option>}
              </select>
              {field === 'visibility' ? (
                <select
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  value={values[field] || common || 'public'}
                  onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                >
                  <option value="public">{t('explorer.visibilityPublic')}</option><option value="private">{t('explorer.visibilityPrivate')}</option>
                </select>
              ) : field === 'category' ? (
                <select
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  value={categoryValue}
                  onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                >
                  {!categoryNames.includes(categoryValue) && (
                    <option value="" disabled>{categoryMixed ? t('explorer.mixedValues') : t('explorer.chooseCategory')}</option>
                  )}
                  {categoryNames.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              ) : (
                <input
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  defaultValue={common}
                  placeholder={common ? undefined : t('explorer.mixedValues')}
                  onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                />
              )}
            </div>
          )
        })}
      </div>
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-vault-text-muted hover:bg-vault-card-hover">{t('common.cancel')}</button>
        <button type="button" disabled={saving || categoryInvalid} onClick={submit} className="rounded-md bg-vault-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{saving ? t('common.loading') : t('common.save')}</button>
      </footer>
    </Modal>
  )
}

export function MergeDialog({ selection, onClose, onDone }: { selection: ExplorerGalleryItem[]; onClose: () => void; onDone: () => void }) {
  const [targetId, setTargetId] = useState(selection[0]?.id ?? 0)
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof api.explorer.mergePreview>> | null>(null)
  const [scalarSources, setScalarSources] = useState<Record<string, number>>({})
  const [working, setWorking] = useState(false)

  useEffect(() => {
    let active = true
    setPreview(null)
    api.explorer.mergePreview({ gallery_ids: selection.map((item) => item.id), target_id: targetId })
      .then((value) => {
        if (!active) return
        setPreview(value)
        setScalarSources(Object.fromEntries(Object.keys(value.scalar_conflicts).map((field) => [field, targetId])))
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : t('common.errorOccurred')))
    return () => { active = false }
  }, [selection, targetId])

  const merge = async () => {
    setWorking(true)
    try {
      await api.explorer.merge({ gallery_ids: selection.map((item) => item.id), target_id: targetId, scalar_sources: scalarSources })
      toast.success(t('explorer.mergeComplete'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setWorking(false)
    }
  }

  return (
    <Modal title={t('explorer.mergeGalleries')} onClose={onClose}>
      <div className="space-y-5 p-5">
        <label className="block text-sm text-vault-text">{t('explorer.mergeTarget')}
          <select value={targetId} onChange={(event) => setTargetId(Number(event.target.value))} className="mt-2 w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2">
            {selection.map((item) => <option key={item.id} value={item.id}>{galleryName(item)}</option>)}
          </select>
        </label>
        {preview ? (
          <>
            <div className="grid grid-cols-3 gap-3 rounded-lg border border-vault-border p-4 text-center">
              <div><p className="text-xl font-semibold text-vault-text">{preview.images.add}</p><p className="text-xs text-vault-text-muted">{t('explorer.imagesAdded')}</p></div>
              <div><p className="text-xl font-semibold text-vault-text">{preview.images.exact_sha_skipped}</p><p className="text-xs text-vault-text-muted">{t('explorer.exactSkipped')}</p></div>
              <div><p className="text-xl font-semibold text-vault-text">{preview.images.similar_kept_for_review}</p><p className="text-xs text-vault-text-muted">{t('explorer.similarReview')}</p></div>
            </div>
            {Object.entries(preview.scalar_conflicts).length > 0 && (
              <div className="space-y-3">
                <p className="text-sm font-medium text-vault-text">{t('explorer.resolveConflicts')}</p>
                {Object.entries(preview.scalar_conflicts).map(([field, choices]) => (
                  <label key={field} className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-3 text-sm text-vault-text-muted">
                    <span>{field}</span>
                    <select value={scalarSources[field] || targetId} onChange={(event) => setScalarSources((current) => ({ ...current, [field]: Number(event.target.value) }))} className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-vault-text">
                      {choices.map((choice) => <option key={choice.gallery_id} value={choice.gallery_id}>{String(choice.value ?? '—')}</option>)}
                    </select>
                  </label>
                ))}
              </div>
            )}
          </>
        ) : <div className="flex justify-center p-6"><Loader2 className="animate-spin" /></div>}
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          {t('explorer.merge404Warning')}
        </div>
      </div>
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-vault-text-muted hover:bg-vault-card-hover">{t('common.cancel')}</button>
        <button type="button" disabled={!preview || working} onClick={merge} className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{working ? t('common.loading') : t('explorer.mergeGalleries')}</button>
      </footer>
    </Modal>
  )
}

export function OrganizeDialog({
  kind,
  selectionBody,
  onClose,
  onDone,
}: {
  kind: 'tags' | 'collections'
  selectionBody: { gallery_ids?: number[]; selection_token?: string; excluded_ids?: number[] }
  onClose: () => void
  onDone: () => void
}) {
  const [operation, setOperation] = useState<'add' | 'remove'>('add')
  const [tagsValue, setTagsValue] = useState('')
  const [collectionId, setCollectionId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const { data: collectionData } = useSWR(kind === 'collections' ? 'explorer-action-collections' : null, api.collections.list)

  const submit = async () => {
    setSaving(true)
    try {
      if (kind === 'tags') {
        const tags = tagsValue.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean)
        await api.explorer.bulkAction({ ...selectionBody, action: operation === 'add' ? 'add_tags' : 'remove_tags', tags })
      } else {
        if (collectionId === null) return
        await api.explorer.bulkAction({ ...selectionBody, action: operation === 'add' ? 'add_collection' : 'remove_collection', collection_id: collectionId })
      }
      toast.success(t('explorer.bulkActionComplete'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={kind === 'tags' ? t('explorer.manageTags') : t('explorer.manageCollections')} onClose={onClose}>
      <div className="space-y-4 p-5">
        <div className="flex rounded-md border border-vault-border p-1">
          <button type="button" onClick={() => setOperation('add')} className={`flex-1 rounded px-3 py-2 text-sm ${operation === 'add' ? 'bg-vault-accent text-white' : 'text-vault-text-muted'}`}>{t('explorer.add')}</button>
          <button type="button" onClick={() => setOperation('remove')} className={`flex-1 rounded px-3 py-2 text-sm ${operation === 'remove' ? 'bg-vault-accent text-white' : 'text-vault-text-muted'}`}>{t('explorer.remove')}</button>
        </div>
        {kind === 'tags' ? (
          <textarea value={tagsValue} onChange={(event) => setTagsValue(event.target.value)} placeholder="artist:name, language:english" rows={5} className="w-full rounded-md border border-vault-border bg-vault-bg p-3 text-sm text-vault-text" />
        ) : (
          <select value={collectionId ?? ''} onChange={(event) => setCollectionId(Number(event.target.value))} className="w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text">
            <option value="">{t('explorer.chooseCollection')}</option>
            {(collectionData?.collections || []).map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
          </select>
        )}
      </div>
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-vault-text-muted hover:bg-vault-card-hover">{t('common.cancel')}</button>
        <button type="button" disabled={saving} onClick={submit} className="rounded-md bg-vault-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{saving ? t('common.loading') : t('common.save')}</button>
      </footer>
    </Modal>
  )
}
