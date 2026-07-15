'use client'

import { Suspense, useState } from 'react'
import { useParams } from 'next/navigation'
import { Check, ImageOff, Pencil, Plus, RotateCcw, X } from 'lucide-react'
import { toast } from 'sonner'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { Pagination } from '@/components/Pagination'
import { useLocale } from '@/components/LocaleProvider'
import {
  useAddDatasetMembers,
  useDataset,
  useExcludeDatasetImage,
  useUpdateDataset,
} from '@/hooks/useDatasets'
import { parseDatasetIds } from '@/lib/datasets'
import { t } from '@/lib/i18n'

const PAGE_LIMIT = 48

function DatasetDetailInner() {
  useLocale()
  const params = useParams()
  const id = Number(params.id)
  const [state, setState] = useState<'included' | 'excluded'>('included')
  const [page, setPage] = useState(0)
  const { data, isLoading, isValidating, mutate } = useDataset(id, {
    state,
    page,
    limit: PAGE_LIMIT,
  })
  const { trigger: update } = useUpdateDataset()
  const { trigger: addMembers } = useAddDatasetMembers()
  const { trigger: excludeImage } = useExcludeDatasetImage()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [galleryIds, setGalleryIds] = useState('')
  const [collectionIds, setCollectionIds] = useState('')
  const [imageIds, setImageIds] = useState('')
  const [busy, setBusy] = useState(false)

  const startEditing = () => {
    setName(data?.name ?? '')
    setDescription(data?.description ?? '')
    setEditing(true)
  }

  const saveMetadata = async () => {
    if (!name.trim()) return
    setBusy(true)
    try {
      await update({ id, data: { name: name.trim(), description: description.trim() || null } })
      await mutate()
      setEditing(false)
      toast.success(t('datasets.updated'))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const handleAdd = async () => {
    setBusy(true)
    try {
      const result = await addMembers({
        id,
        selection: {
          gallery_ids: parseDatasetIds(galleryIds),
          collection_ids: parseDatasetIds(collectionIds),
          image_ids: parseDatasetIds(imageIds),
        },
      })
      setGalleryIds('')
      setCollectionIds('')
      setImageIds('')
      setShowAdd(false)
      setState('included')
      setPage(0)
      await mutate()
      toast.success(t('datasets.membersAdded', { count: String(result.added) }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const handleImageState = async (imageId: number) => {
    try {
      if (state === 'included') {
        await excludeImage({ id, imageId })
        toast.success(t('datasets.imageExcluded'))
      } else {
        await addMembers({ id, selection: { image_ids: [imageId] } })
        toast.success(t('datasets.imageRestored'))
      }
      await mutate()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <BackButton fallback="/datasets" />
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="max-w-2xl space-y-2">
              <input
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-lg border border-vault-accent bg-vault-input px-3 py-2 text-xl font-bold text-vault-text outline-none"
              />
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="w-full resize-y rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text outline-none"
                rows={2}
                placeholder={t('datasets.descriptionPlaceholder')}
              />
              <div className="flex gap-2">
                <button
                  onClick={saveMetadata}
                  disabled={busy || !name.trim()}
                  className="rounded bg-vault-accent p-2 text-vault-accent-fg disabled:opacity-50"
                  aria-label={t('common.save')}
                >
                  <Check size={16} />
                </button>
                <button
                  onClick={() => setEditing(false)}
                  disabled={busy}
                  className="rounded border border-vault-border p-2 text-vault-text-secondary"
                  aria-label={t('common.cancel')}
                >
                  <X size={16} />
                </button>
              </div>
            </div>
          ) : (
            <div className="group/title">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-2xl font-bold text-vault-text">{data?.name ?? '…'}</h1>
                <button
                  onClick={startEditing}
                  className="rounded p-1 text-vault-text-secondary opacity-100 can-hover:opacity-0 can-hover:group-hover/title:opacity-100"
                  aria-label={t('datasets.edit')}
                >
                  <Pencil size={15} />
                </button>
              </div>
              <p className="mt-1 text-sm text-vault-text-secondary">
                {data?.description || t('datasets.noDescription')}
              </p>
            </div>
          )}
        </div>
        <button
          onClick={() => setShowAdd((value) => !value)}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-vault-accent px-3 py-2 text-sm font-medium text-vault-accent-fg"
        >
          <Plus size={16} />
          {t('datasets.addMembers')}
        </button>
      </div>

      {showAdd && (
        <section className="space-y-3 rounded-xl border border-vault-border bg-vault-card p-4">
          <p className="text-sm text-vault-text-secondary">{t('datasets.selectionHint')}</p>
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['datasets.galleryIds', galleryIds, setGalleryIds],
              ['datasets.collectionIds', collectionIds, setCollectionIds],
              ['datasets.imageIds', imageIds, setImageIds],
            ].map(([label, value, setter]) => (
              <label key={label as string} className="space-y-1 text-sm text-vault-text-secondary">
                <span>{t(label as string)}</span>
                <input
                  value={value as string}
                  onChange={(event) => (setter as (value: string) => void)(event.target.value)}
                  inputMode="numeric"
                  className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
                  placeholder={t('datasets.idsPlaceholder')}
                />
              </label>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleAdd}
              disabled={busy || !(galleryIds || collectionIds || imageIds)}
              className="rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-vault-accent-fg disabled:opacity-50"
            >
              {busy ? t('common.loading') : t('datasets.addMembers')}
            </button>
            <button
              onClick={() => setShowAdd(false)}
              disabled={busy}
              className="rounded-lg border border-vault-border px-4 py-2 text-sm text-vault-text-secondary"
            >
              {t('common.cancel')}
            </button>
          </div>
        </section>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-vault-border">
        <div className="flex">
          {(['included', 'excluded'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => {
                setState(tab)
                setPage(0)
              }}
              className={`border-b-2 px-4 py-2 text-sm transition-colors ${state === tab ? 'border-vault-accent text-vault-accent' : 'border-transparent text-vault-text-secondary'}`}
            >
              {tab === 'included'
                ? t('datasets.includedCount', { count: String(data?.member_count ?? 0) })
                : t('datasets.excludedCount', { count: String(data?.excluded_count ?? 0) })}
            </button>
          ))}
        </div>
        {data && (
          <span className="pb-2 text-xs text-vault-text-secondary">
            {t('datasets.galleryCount', { count: String(data.gallery_count) })}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-16">
          <LoadingSpinner size="lg" />
        </div>
      ) : !data?.images.length ? (
        <div className="flex flex-col items-center gap-3 py-16 text-vault-text-secondary">
          <ImageOff size={48} className="opacity-30" />
          <p>
            {state === 'included' ? t('datasets.noIncludedImages') : t('datasets.noExcludedImages')}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
          {data.images.map((image) => (
            <article
              key={image.id}
              className="group overflow-hidden rounded-lg border border-vault-border bg-vault-card"
            >
              <div className="relative aspect-square bg-vault-bg">
                <img
                  src={image.thumb_url}
                  alt={image.filename}
                  className="h-full w-full object-cover"
                  loading="lazy"
                />
                <button
                  onClick={() => handleImageState(image.id)}
                  className={`absolute right-1.5 top-1.5 rounded p-1.5 text-white opacity-100 shadow can-hover:opacity-0 can-hover:group-hover:opacity-100 ${state === 'included' ? 'bg-red-600/90 hover:bg-red-500' : 'bg-green-600/90 hover:bg-green-500'}`}
                  aria-label={
                    state === 'included' ? t('datasets.excludeImage') : t('datasets.restoreImage')
                  }
                >
                  {state === 'included' ? <X size={14} /> : <RotateCcw size={14} />}
                </button>
              </div>
              <div className="space-y-0.5 p-2 text-xs">
                <p className="truncate text-vault-text" title={image.gallery_title}>
                  {image.gallery_title}
                </p>
                <p className="truncate text-vault-text-secondary">
                  #{image.page_num} · {image.source}
                </p>
              </div>
            </article>
          ))}
        </div>
      )}

      {data && data.total > PAGE_LIMIT && (
        <Pagination
          page={page}
          total={data.total}
          pageSize={PAGE_LIMIT}
          onChange={setPage}
          isLoading={isValidating}
        />
      )}
    </div>
  )
}

export default function DatasetDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <LoadingSpinner size="lg" />
        </div>
      }
    >
      <DatasetDetailInner />
    </Suspense>
  )
}
