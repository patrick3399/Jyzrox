'use client'
import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

/**
 * Full tag translations browse/search panel. Available to every logged-in
 * role; inline editing (via the existing upsertTranslation endpoint) is
 * admin-only. See docs/superpowers/specs/2026-07-12-tag-translations-browse-design.md.
 */

const LANGUAGE_OPTIONS: { value: string; label: string }[] = [
  { value: 'zh-TW', label: '中文（繁）' },
  { value: 'zh', label: '中文（简）' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
]

/** zh-TW is a display-layer variant of the DB "zh" language; writes always target "zh". */
function toDbLanguage(language: string): string {
  return language === 'zh-TW' ? 'zh' : language
}

interface TagTranslationsPanelProps {
  isAdmin: boolean
}

export default function TagTranslationsPanel({ isAdmin }: TagTranslationsPanelProps) {
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [namespace, setNamespace] = useState('')
  const [language, setLanguage] = useState('zh')
  const [offset, setOffset] = useState(0)
  const limit = 50

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    setOffset(0)
  }, [debouncedSearch, namespace, language])

  const { data, mutate } = useSWR(
    ['tags-translations-browse', debouncedSearch, namespace, language, offset, limit],
    ([, q, ns, lang, off, lim]: [string, string, string, string, number, number]) =>
      api.tags.translationsBrowse({
        q: q || undefined,
        namespace: ns || undefined,
        language: lang,
        limit: lim,
        offset: off,
      }),
  )

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = total > 0 ? Math.ceil(total / limit) : 0
  const page = offset / limit

  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  const startEdit = useCallback((key: string, value: string) => {
    setEditingKey(key)
    setEditValue(value)
  }, [])

  const cancelEdit = useCallback(() => {
    setEditingKey(null)
    setEditValue('')
  }, [])

  const handleSave = useCallback(
    async (ns: string, name: string) => {
      try {
        await api.tags.upsertTranslation({
          namespace: ns,
          name,
          language: toDbLanguage(language),
          translation: editValue.trim(),
        })
        toast.success(t('tags.translationSaved'))
        setEditingKey(null)
        setEditValue('')
        mutate()
      } catch {
        toast.error(t('tags.translationFailed'))
      }
    },
    [language, editValue, mutate],
  )

  return (
    <>
      {/* Filters */}
      <div className="mb-6 flex gap-3 flex-wrap items-center">
        <input
          type="text"
          placeholder={t('tags.translationsBrowseSearchPlaceholder')}
          className="px-3 py-2 w-64 bg-vault-input border border-vault-border rounded-lg text-vault-text placeholder-vault-text-muted outline-none focus:border-vault-border-hover text-sm"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <input
          type="text"
          placeholder={t('tags.namespacePlaceholder')}
          className="px-3 py-2 w-48 bg-vault-input border border-vault-border rounded-lg text-vault-text placeholder-vault-text-muted outline-none focus:border-vault-border-hover text-sm"
          value={namespace}
          onChange={(e) => setNamespace(e.target.value)}
        />
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          aria-label={t('tags.translationLanguage')}
          className="px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-vault-text outline-none focus:border-vault-border-hover text-sm"
        >
          {LANGUAGE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Results table */}
      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <table className="w-full text-left">
          <thead className="bg-vault-card-hover">
            <tr>
              <th className="p-3 text-sm text-vault-text-muted font-medium">
                {t('tags.namespace')}
              </th>
              <th className="p-3 text-sm text-vault-text-muted font-medium">{t('tags.name')}</th>
              <th className="p-3 text-sm text-vault-text-muted font-medium">
                {t('tags.translationsBrowseTranslationHeader')}
              </th>
              {isAdmin && <th className="p-3 text-sm text-vault-text-muted font-medium" />}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const key = `${item.namespace}:${item.name}`
              const isEditing = editingKey === key
              return (
                <tr key={key} className="border-t border-vault-border">
                  <td className="p-3 text-vault-text-secondary text-sm">{item.namespace}</td>
                  <td className="p-3 font-mono text-vault-accent text-sm">{item.name}</td>
                  <td className="p-3 text-sm">
                    {isEditing ? (
                      <input
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSave(item.namespace, item.name)}
                        className="p-1.5 w-full bg-vault-input border border-vault-border rounded text-sm outline-none text-vault-text"
                        autoFocus
                      />
                    ) : (
                      item.translation
                    )}
                  </td>
                  {isAdmin && (
                    <td className="p-3 text-sm text-right">
                      {isEditing ? (
                        <div className="flex gap-1 justify-end">
                          <button
                            type="button"
                            onClick={() => handleSave(item.namespace, item.name)}
                            className="px-2 py-1 text-xs bg-vault-accent hover:bg-vault-accent/90 rounded text-white transition-colors"
                          >
                            {t('common.save')}
                          </button>
                          <button
                            type="button"
                            onClick={cancelEdit}
                            className="px-2 py-1 text-xs text-vault-text-muted hover:text-vault-text transition-colors"
                          >
                            {t('common.cancel')}
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => startEdit(key, item.translation)}
                          aria-label={t('tags.editTranslation')}
                          title={t('tags.editTranslation')}
                          className="flex items-center gap-1 px-2 py-1 text-xs text-vault-text-secondary hover:text-vault-accent transition-colors ml-auto"
                        >
                          <Pencil size={12} />
                          {t('tags.editTranslation')}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
            {items.length === 0 && (
              <tr>
                <td className="p-4 text-vault-text-muted" colSpan={isAdmin ? 4 : 3}>
                  {t('tags.translationsBrowseEmpty')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Offset pagination */}
      {totalPages > 1 && (
        <div className="flex gap-2 mt-4 items-center">
          <button
            type="button"
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={page === 0}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-vault-card border border-vault-border hover:bg-vault-card-hover disabled:opacity-30 text-sm transition-colors"
          >
            <ChevronLeft size={14} /> {t('tags.prev')}
          </button>
          <span className="text-sm text-vault-text-secondary">
            {page + 1} / {totalPages} (
            {t('tags.translationsBrowseTotal', { total: String(total) })})
          </span>
          <button
            type="button"
            onClick={() => setOffset(Math.min((totalPages - 1) * limit, offset + limit))}
            disabled={page >= totalPages - 1}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-vault-card border border-vault-border hover:bg-vault-card-hover disabled:opacity-30 text-sm transition-colors"
          >
            {t('tags.next')} <ChevronRight size={14} />
          </button>
        </div>
      )}
    </>
  )
}
