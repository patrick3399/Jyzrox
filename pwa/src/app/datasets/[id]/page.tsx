'use client'

import { Suspense, useState } from 'react'
import { useParams } from 'next/navigation'
import {
  Check,
  ImageOff,
  MessageSquareText,
  Pencil,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AppImage } from '@/components/AppImage'
import { Pagination } from '@/components/Pagination'
import { useLocale } from '@/components/LocaleProvider'
import {
  useAddDatasetMembers,
  useApplyDatasetFilters,
  useDataset,
  useExcludeDatasetImage,
  usePreviewDatasetFilters,
  useUpdateDataset,
} from '@/hooks/useDatasets'
import { parseDatasetIds } from '@/lib/datasets'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { DatasetFilterConfig, DatasetFilterReport } from '@/lib/types'

const PAGE_LIMIT = 48

function optionalNumber(value: string): number | null {
  return value.trim() ? Number(value) : null
}

function exclusionReasonLabel(reason: string): string {
  if (reason === 'manual') return t('datasets.exclusionManual')
  if (reason === 'min_resolution') return t('datasets.exclusionMinResolution')
  if (reason === 'aspect_ratio') return t('datasets.exclusionAspectRatio')
  if (reason === 'phash_duplicate') return t('datasets.exclusionPhashDuplicate')
  return reason
}

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
  const { trigger: previewFilters } = usePreviewDatasetFilters()
  const { trigger: applyFilters } = useApplyDatasetFilters()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [galleryIds, setGalleryIds] = useState('')
  const [collectionIds, setCollectionIds] = useState('')
  const [imageIds, setImageIds] = useState('')
  const [tagQuery, setTagQuery] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [showCaptions, setShowCaptions] = useState(false)
  const [triggerWord, setTriggerWord] = useState('')
  const [captionSearch, setCaptionSearch] = useState('')
  const [captionReplacement, setCaptionReplacement] = useState('')
  const [minWidth, setMinWidth] = useState('')
  const [minHeight, setMinHeight] = useState('')
  const [maxAspectRatio, setMaxAspectRatio] = useState('')
  const [phashDistance, setPhashDistance] = useState('')
  const [filterPreview, setFilterPreview] = useState<DatasetFilterReport | null>(null)
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
      await update({
        id,
        data: {
          name: name.trim(),
          description: description.trim() || null,
        },
      })
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
          tag_query: tagQuery.trim() || undefined,
        },
      })
      setGalleryIds('')
      setCollectionIds('')
      setImageIds('')
      setTagQuery('')
      setShowAdd(false)
      setState('included')
      setPage(0)
      await mutate()
      toast.success(t('datasets.membersAdded', { count: String(result.added) }))
      if (result.tag_query_truncated) toast.warning(t('datasets.tagQueryTruncated'))
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

  const openFilters = () => {
    const filters = data?.selection_spec.filters
    setMinWidth(filters?.min_width == null ? '' : String(filters.min_width))
    setMinHeight(filters?.min_height == null ? '' : String(filters.min_height))
    setMaxAspectRatio(filters?.max_aspect_ratio == null ? '' : String(filters.max_aspect_ratio))
    setPhashDistance(filters?.phash_distance == null ? '' : String(filters.phash_distance))
    setFilterPreview(null)
    setShowFilters(true)
  }

  const filterConfig = (): DatasetFilterConfig => ({
    min_width: optionalNumber(minWidth),
    min_height: optionalNumber(minHeight),
    max_aspect_ratio: optionalNumber(maxAspectRatio),
    phash_distance: optionalNumber(phashDistance),
  })

  const handlePreviewFilters = async () => {
    setBusy(true)
    try {
      setFilterPreview(await previewFilters({ id, filters: filterConfig() }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const handleApplyFilters = async () => {
    setBusy(true)
    try {
      const result = await applyFilters({ id, filters: filterConfig() })
      setFilterPreview(result)
      await mutate()
      toast.success(t('datasets.filtersApplied', { count: String(result.changed) }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const handleCaptionBatch = async (
    operation: 'prepend_trigger' | 'search_replace',
  ) => {
    setBusy(true)
    try {
      const result =
        operation === 'prepend_trigger'
          ? await api.datasets.batchCaptions(id, {
              operation,
              trigger_word: triggerWord,
            })
          : await api.datasets.batchCaptions(id, {
              operation,
              search: captionSearch,
              replacement: captionReplacement,
            })
      await mutate()
      toast.success(t('datasets.captionsChanged', { count: String(result.changed) }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
    } finally {
      setBusy(false)
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
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <button
            onClick={() => setShowCaptions((value) => !value)}
            className="flex items-center gap-1.5 rounded-lg border border-vault-border bg-vault-card px-3 py-2 text-sm font-medium text-vault-text transition-colors hover:border-vault-accent/50"
          >
            <MessageSquareText size={16} />
            {t('datasets.captions')}
          </button>
          <button
            onClick={openFilters}
            className="flex items-center gap-1.5 rounded-lg border border-vault-border bg-vault-card px-3 py-2 text-sm font-medium text-vault-text transition-colors hover:border-vault-accent/50"
          >
            <SlidersHorizontal size={16} />
            {t('datasets.filters')}
          </button>
          <button
            onClick={() => setShowAdd((value) => !value)}
            className="flex items-center gap-1.5 rounded-lg bg-vault-accent px-3 py-2 text-sm font-medium text-vault-accent-fg"
          >
            <Plus size={16} />
            {t('datasets.addMembers')}
          </button>
        </div>
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
          <label className="block space-y-1 text-sm text-vault-text-secondary">
            <span>{t('datasets.tagQuery')}</span>
            <input
              value={tagQuery}
              onChange={(event) => setTagQuery(event.target.value)}
              className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
              placeholder={t('datasets.tagQueryPlaceholder')}
            />
            <span className="block text-xs">{t('datasets.tagQueryHint')}</span>
          </label>
          <div className="flex gap-2">
            <button
              onClick={handleAdd}
              disabled={busy || !(galleryIds || collectionIds || imageIds || tagQuery)}
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

      {showCaptions && (
        <section className="space-y-4 rounded-xl border border-vault-border bg-vault-card p-4">
          <div>
            <h2 className="font-semibold text-vault-text">{t('datasets.captionReview')}</h2>
            <p className="mt-1 text-sm text-vault-text-secondary">{t('datasets.captionReviewHint')}</p>
          </div>
          <div className="grid gap-2 md:grid-cols-[1fr_auto]">
            <input
              value={triggerWord}
              onChange={(event) => setTriggerWord(event.target.value)}
              placeholder={t('datasets.triggerWordPlaceholder')}
              className="rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
            />
            <button
              type="button"
              disabled={busy || !triggerWord.trim()}
              onClick={() => handleCaptionBatch('prepend_trigger')}
              className="rounded-lg border border-vault-accent px-4 py-2 text-sm text-vault-accent disabled:opacity-50"
            >
              {t('datasets.prependTrigger')}
            </button>
          </div>
          <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
            <input
              value={captionSearch}
              onChange={(event) => setCaptionSearch(event.target.value)}
              placeholder={t('datasets.captionSearch')}
              className="rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
            />
            <input
              value={captionReplacement}
              onChange={(event) => setCaptionReplacement(event.target.value)}
              placeholder={t('datasets.captionReplacement')}
              className="rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
            />
            <button
              type="button"
              disabled={busy || !captionSearch}
              onClick={() => handleCaptionBatch('search_replace')}
              className="rounded-lg border border-vault-border px-4 py-2 text-sm text-vault-text-secondary disabled:opacity-50"
            >
              {t('datasets.replaceCaptions')}
            </button>
          </div>
        </section>
      )}

      {showFilters && (
        <section className="space-y-4 rounded-xl border border-vault-border bg-vault-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold text-vault-text">{t('datasets.filtersTitle')}</h2>
              <p className="mt-1 text-sm text-vault-text-secondary">{t('datasets.filtersHint')}</p>
            </div>
            <button
              onClick={() => setShowFilters(false)}
              className="rounded p-1 text-vault-text-secondary hover:text-vault-text"
              aria-label={t('common.close')}
            >
              <X size={16} />
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-sm text-vault-text-secondary">
              <span>{t('datasets.minWidth')}</span>
              <input
                type="number"
                min="1"
                value={minWidth}
                onChange={(event) => {
                  setMinWidth(event.target.value)
                  setFilterPreview(null)
                }}
                className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
                placeholder="1024"
              />
            </label>
            <label className="space-y-1 text-sm text-vault-text-secondary">
              <span>{t('datasets.minHeight')}</span>
              <input
                type="number"
                min="1"
                value={minHeight}
                onChange={(event) => {
                  setMinHeight(event.target.value)
                  setFilterPreview(null)
                }}
                className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
                placeholder="1024"
              />
            </label>
            <label className="space-y-1 text-sm text-vault-text-secondary">
              <span>{t('datasets.maxAspectRatio')}</span>
              <input
                type="number"
                min="1.01"
                max="100"
                step="0.1"
                value={maxAspectRatio}
                onChange={(event) => {
                  setMaxAspectRatio(event.target.value)
                  setFilterPreview(null)
                }}
                className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
                placeholder="4"
              />
            </label>
            <label className="space-y-1 text-sm text-vault-text-secondary">
              <span>{t('datasets.phashDistance')}</span>
              <input
                type="number"
                min="0"
                max="64"
                value={phashDistance}
                onChange={(event) => {
                  setPhashDistance(event.target.value)
                  setFilterPreview(null)
                }}
                className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text outline-none focus:ring-1 focus:ring-vault-accent"
                placeholder="6"
              />
            </label>
          </div>
          {filterPreview && (
            <div className="grid gap-2 rounded-lg bg-vault-bg p-3 text-sm sm:grid-cols-3">
              <span className="text-vault-text">
                {t('datasets.previewAutoExcluded', { count: String(filterPreview.auto_excluded) })}
              </span>
              <span className="text-vault-text">
                {t('datasets.previewRemaining', { count: String(filterPreview.remaining) })}
              </span>
              <span className="text-vault-text-secondary">
                {t('datasets.previewRestored', { count: String(filterPreview.would_restore) })}
              </span>
              <span className="text-vault-text-secondary">
                {t('datasets.previewResolution', {
                  count: String(filterPreview.reasons.min_resolution),
                })}
              </span>
              <span className="text-vault-text-secondary">
                {t('datasets.previewAspectRatio', {
                  count: String(filterPreview.reasons.aspect_ratio),
                })}
              </span>
              <span className="text-vault-text-secondary">
                {t('datasets.previewUnknown', { count: String(filterPreview.unknown_dimensions) })}
              </span>
              <span className="text-vault-text-secondary">
                {t('datasets.previewPhashDuplicate', {
                  count: String(filterPreview.reasons.phash_duplicate),
                })}
              </span>
              <span className="text-vault-text-secondary">
                {t('datasets.previewUnknownPhash', { count: String(filterPreview.unknown_phash) })}
              </span>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handlePreviewFilters}
              disabled={busy}
              className="rounded-lg border border-vault-accent px-4 py-2 text-sm font-medium text-vault-accent disabled:opacity-50"
            >
              {t('datasets.previewFilters')}
            </button>
            <button
              onClick={handleApplyFilters}
              disabled={busy}
              className="rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-vault-accent-fg disabled:opacity-50"
            >
              {busy ? t('common.loading') : t('datasets.applyFilters')}
            </button>
            <button
              onClick={() => {
                setMinWidth('')
                setMinHeight('')
                setMaxAspectRatio('')
                setFilterPreview(null)
              }}
              disabled={busy}
              className="rounded-lg border border-vault-border px-4 py-2 text-sm text-vault-text-secondary disabled:opacity-50"
            >
              {t('datasets.clearFilters')}
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
        <div
          className={`grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 ${showCaptions ? 'xl:grid-cols-4' : 'xl:grid-cols-6'}`}
        >
          {data.images.map((image) => (
            <article
              key={image.id}
              className="group overflow-hidden rounded-lg border border-vault-border bg-vault-card"
            >
              <div className="relative aspect-square bg-vault-bg">
                <AppImage
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
                {image.exclusion_reason && (
                  <p className="truncate text-red-400">
                    {exclusionReasonLabel(image.exclusion_reason)}
                  </p>
                )}
                {showCaptions && state === 'included' && (
                  <textarea
                    defaultValue={image.caption ?? ''}
                    rows={4}
                    aria-label={t('datasets.imageCaption')}
                    onBlur={async (event) => {
                      const caption = event.currentTarget.value.trim() || null
                      if (caption === image.caption) return
                      try {
                        await api.datasets.updateCaption(id, image.id, caption)
                        toast.success(t('common.saved'))
                      } catch (error) {
                        toast.error(error instanceof Error ? error.message : t('common.error'))
                      }
                    }}
                    className="mt-2 w-full resize-y rounded border border-vault-border bg-vault-input p-2 text-xs text-vault-text"
                  />
                )}
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
