'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { useSWRConfig } from 'swr'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { useCategoryRegistry } from '@/hooks/useCategoryRegistry'
import { api } from '@/lib/api'
import { CATEGORY_PALETTE } from '@/lib/categoryPalette'
import { t } from '@/lib/i18n'
import type { GalleryCategoryDef } from '@/lib/types'

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : t('common.failedToLoad')
}

function ColorPicker({
  palette,
  value,
  onChange,
}: {
  palette: string[]
  value: string
  onChange: (color: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {palette.map((key) => (
        <button
          key={key}
          type="button"
          aria-label={key}
          aria-pressed={key === value}
          onClick={() => onChange(key)}
          className={`h-5 w-5 rounded-full ${CATEGORY_PALETTE[key]?.swatch ?? 'bg-gray-500'} ${
            key === value ? 'ring-2 ring-vault-accent ring-offset-1 ring-offset-vault-card' : ''
          }`}
        />
      ))}
    </div>
  )
}

export default function CategoriesSettingsPage() {
  const isAdmin = useAdminGuard()
  const { data, mutate, isLoading } = useCategoryRegistry()
  const { mutate: mutateGlobal } = useSWRConfig()
  const [newName, setNewName] = useState('')
  const [newColor, setNewColor] = useState('gray')
  const [backfillMatched, setBackfillMatched] = useState<number | null>(null)

  if (!isAdmin) return null
  if (isLoading || !data) return <LoadingSpinner />

  const builtin = data.categories.filter((c) => c.is_builtin)
  const custom = data.categories.filter((c) => !c.is_builtin)

  // The library filter dropdown reads its own key; refresh it as well.
  const refresh = async () => {
    await mutate()
    await mutateGlobal('library/categories')
  }

  const handleAdd = async () => {
    const name = newName.trim()
    if (!name) return
    try {
      await api.galleryCategories.create({ name, color: newColor })
      setNewName('')
      toast.success(t('categories.created'))
      await refresh()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const handleColor = async (category: GalleryCategoryDef, color: string) => {
    try {
      await api.galleryCategories.updateColor(category.id, color)
      toast.success(t('categories.colorUpdated'))
      await refresh()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const handleDelete = async (category: GalleryCategoryDef) => {
    const message = t('categories.deleteConfirm', {
      name: category.name,
      count: String(category.gallery_count),
    })
    if (!window.confirm(message)) return
    try {
      await api.galleryCategories.remove(category.id)
      toast.success(t('categories.deleted'))
      await refresh()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const handlePreview = async () => {
    try {
      const result = await api.galleryCategories.backfill(true)
      setBackfillMatched(result.matched)
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const handleApply = async () => {
    try {
      const result = await api.galleryCategories.backfill(false)
      setBackfillMatched(null)
      toast.success(t('categories.backfillApplied', { count: String(result.applied) }))
      await refresh()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const card = 'bg-vault-card border border-vault-border rounded-lg p-4'

  return (
    <div className="max-w-2xl space-y-6">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold text-vault-text">{t('settingsCategory.categories')}</h1>
      <section className={card}>
        <h2 className="mb-3 text-sm font-medium text-vault-text">{t('categories.builtin')}</h2>
        <ul className="flex flex-wrap gap-2">
          {builtin.map((c) => (
            <li
              key={c.id}
              className="flex items-center gap-2 rounded-full border border-vault-border px-3 py-1 text-sm text-vault-text"
            >
              <span className={`h-3 w-3 rounded-full ${CATEGORY_PALETTE[c.color]?.swatch ?? 'bg-gray-500'}`} />
              {c.name}
              <span className="text-xs text-vault-text-muted">
                {t('categories.galleryCount', { count: String(c.gallery_count) })}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className={card}>
        <h2 className="mb-3 text-sm font-medium text-vault-text">{t('categories.custom')}</h2>
        <ul className="space-y-3">
          {custom.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-3">
              <span className="min-w-24 text-sm text-vault-text">{c.name}</span>
              <ColorPicker
                palette={data.palette}
                value={c.color}
                onChange={(color) => handleColor(c, color)}
              />
              <span className="text-xs text-vault-text-muted">
                {t('categories.galleryCount', { count: String(c.gallery_count) })}
              </span>
              <button
                type="button"
                onClick={() => handleDelete(c)}
                className="ml-auto text-xs text-red-400 hover:text-red-300"
              >
                {t('categories.delete')}
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-vault-border pt-4">
          <input
            type="text"
            value={newName}
            maxLength={64}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t('categories.namePlaceholder')}
            className="rounded border border-vault-border bg-vault-input px-2 py-1 text-sm text-vault-text focus:outline-none"
          />
          <ColorPicker palette={data.palette} value={newColor} onChange={setNewColor} />
          <button
            type="button"
            onClick={handleAdd}
            disabled={!newName.trim()}
            className="rounded bg-vault-accent px-3 py-1 text-sm text-white disabled:opacity-50"
          >
            {t('categories.add')}
          </button>
        </div>
      </section>

      <section className={card}>
        <h2 className="mb-1 text-sm font-medium text-vault-text">{t('categories.backfillTitle')}</h2>
        <p className="mb-3 text-xs text-vault-text-muted">{t('categories.backfillDesc')}</p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handlePreview}
            className="rounded border border-vault-border px-3 py-1 text-sm text-vault-text"
          >
            {t('categories.backfillPreview')}
          </button>
          {backfillMatched !== null && (
            <>
              <span className="text-sm text-vault-text-muted">
                {t('categories.backfillMatched', { count: String(backfillMatched) })}
              </span>
              {backfillMatched > 0 && (
                <button
                  type="button"
                  onClick={handleApply}
                  className="rounded bg-vault-accent px-3 py-1 text-sm text-white"
                >
                  {t('categories.backfillApply')}
                </button>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  )
}
