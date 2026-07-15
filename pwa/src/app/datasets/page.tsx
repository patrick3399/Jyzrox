'use client'

import { Suspense, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Database, Image as ImageIcon, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { useLocale } from '@/components/LocaleProvider'
import { useCreateDataset, useDatasets, useDeleteDataset } from '@/hooks/useDatasets'
import { parseDatasetIds } from '@/lib/datasets'
import { t } from '@/lib/i18n'

function DatasetsPageInner() {
  useLocale()
  const router = useRouter()
  const { data, isLoading, mutate } = useDatasets()
  const { trigger: create } = useCreateDataset()
  const { trigger: remove } = useDeleteDataset()
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [galleryIds, setGalleryIds] = useState('')
  const [collectionIds, setCollectionIds] = useState('')
  const [imageIds, setImageIds] = useState('')
  const [busy, setBusy] = useState(false)

  const resetForm = () => {
    setName('')
    setDescription('')
    setGalleryIds('')
    setCollectionIds('')
    setImageIds('')
    setShowCreate(false)
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    setBusy(true)
    try {
      const created = await create({
        name: name.trim(),
        description: description.trim() || undefined,
        gallery_ids: parseDatasetIds(galleryIds),
        collection_ids: parseDatasetIds(collectionIds),
        image_ids: parseDatasetIds(imageIds),
      })
      await mutate()
      toast.success(t('datasets.created'))
      resetForm()
      router.push(`/datasets/${created.id}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('datasets.confirmDelete'))) return
    try {
      await remove(id)
      await mutate()
      toast.success(t('datasets.deleted'))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-vault-text">{t('datasets.title')}</h1>
          <p className="mt-1 text-sm text-vault-text-secondary">{t('datasets.subtitle')}</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 rounded-lg bg-vault-accent px-3 py-2 text-sm font-medium text-vault-accent-fg transition-colors hover:bg-vault-accent-hover"
        >
          <Plus size={16} />
          {t('datasets.create')}
        </button>
      </div>

      {showCreate && (
        <section className="space-y-4 rounded-xl border border-vault-border bg-vault-card p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-sm text-vault-text-secondary">
              <span>{t('datasets.name')}</span>
              <input
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
                placeholder={t('datasets.namePlaceholder')}
              />
            </label>
            <label className="space-y-1 text-sm text-vault-text-secondary">
              <span>{t('datasets.description')}</span>
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
                placeholder={t('datasets.descriptionPlaceholder')}
              />
            </label>
          </div>
          <p className="text-xs text-vault-text-secondary">{t('datasets.selectionHint')}</p>
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
              onClick={handleCreate}
              disabled={busy || !name.trim()}
              className="rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-vault-accent-fg disabled:opacity-50"
            >
              {busy ? t('common.loading') : t('datasets.create')}
            </button>
            <button
              onClick={resetForm}
              disabled={busy}
              className="rounded-lg border border-vault-border px-4 py-2 text-sm text-vault-text-secondary"
            >
              {t('common.cancel')}
            </button>
          </div>
        </section>
      )}

      {isLoading ? (
        <div className="flex justify-center py-16">
          <LoadingSpinner size="lg" />
        </div>
      ) : !data?.datasets.length ? (
        <div className="flex flex-col items-center gap-3 py-16 text-vault-text-secondary">
          <Database size={48} className="opacity-30" />
          <p>{t('datasets.empty')}</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.datasets.map((dataset) => (
            <article
              key={dataset.id}
              className="group rounded-xl border border-vault-border bg-vault-card p-4 transition-colors hover:border-vault-accent/50"
            >
              <button
                className="w-full text-left"
                onClick={() => router.push(`/datasets/${dataset.id}`)}
              >
                <div className="flex items-start gap-3">
                  <Database className="mt-0.5 shrink-0 text-vault-accent" size={20} />
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate font-semibold text-vault-text">{dataset.name}</h2>
                    <p className="mt-1 line-clamp-2 min-h-10 text-sm text-vault-text-secondary">
                      {dataset.description || t('datasets.noDescription')}
                    </p>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-xs text-vault-text-secondary">
                  <span className="flex items-center gap-1 rounded-full bg-vault-bg px-2 py-1">
                    <ImageIcon size={12} />
                    {t('datasets.imageCount', { count: String(dataset.member_count) })}
                  </span>
                  <span className="rounded-full bg-vault-bg px-2 py-1">
                    {t('datasets.galleryCount', { count: String(dataset.gallery_count) })}
                  </span>
                  {dataset.excluded_count > 0 && (
                    <span className="rounded-full bg-red-500/10 px-2 py-1 text-red-400">
                      {t('datasets.excludedCount', { count: String(dataset.excluded_count) })}
                    </span>
                  )}
                </div>
              </button>
              <div className="mt-3 flex justify-end border-t border-vault-border pt-3">
                <button
                  onClick={() => handleDelete(dataset.id)}
                  aria-label={t('datasets.delete')}
                  className="rounded p-1.5 text-vault-text-secondary transition-colors hover:bg-red-500/10 hover:text-red-400"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

export default function DatasetsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <LoadingSpinner size="lg" />
        </div>
      }
    >
      <DatasetsPageInner />
    </Suspense>
  )
}
