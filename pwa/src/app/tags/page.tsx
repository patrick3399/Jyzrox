'use client'
import { useState, useCallback } from 'react'
import { Tags, ChevronLeft, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { EmptyState } from '@/components/EmptyState'
import { t } from '@/lib/i18n'
import type { TagItem } from '@/lib/types'

export default function TagsPage() {
  const [search, setSearch] = useState('')
  const [nsFilter, setNsFilter] = useState('')
  const [page, setPage] = useState(0)
  // cursor-based pagination state for tags
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [cursorHistory, setCursorHistory] = useState<(string | undefined)[]>([])
  const limit = 50

  const [selectedTag, setSelectedTag] = useState<TagItem | null>(null)

  // Include cursor in SWR key for correct cache segmentation
  const { data: tagData } = useSWR(['tags', search, nsFilter, cursor ?? page], () =>
    api.tags.list({
      prefix: search || undefined,
      namespace: nsFilter || undefined,
      limit,
      // When cursor is active use it; otherwise fall back to offset
      ...(cursor ? { cursor } : { offset: page * limit }),
    }),
  )

  const isCursorMode = tagData !== undefined && tagData.next_cursor !== undefined
  const hasNextTag = isCursorMode ? (tagData?.has_next ?? false) : false
  const hasPrevTag = cursorHistory.length > 0

  const handleNextTagCursor = useCallback(() => {
    if (!tagData?.next_cursor) return
    setCursorHistory((prev) => [...prev, cursor])
    setCursor(tagData.next_cursor ?? undefined)
  }, [tagData?.next_cursor, cursor])

  const handlePrevTagCursor = useCallback(() => {
    if (cursorHistory.length === 0) return
    const prev = [...cursorHistory]
    const restored = prev.pop()
    setCursorHistory(prev)
    setCursor(restored)
  }, [cursorHistory])

  const resetTagPagination = useCallback(() => {
    setPage(0)
    setCursor(undefined)
    setCursorHistory([])
  }, [])

  const { data: aliases, mutate: mutateAliases } = useSWR(
    selectedTag ? ['aliases', selectedTag.id] : null,
    () => api.tags.listAliases({ tag_id: selectedTag!.id }),
  )

  const { data: implications, mutate: mutateImplications } = useSWR(
    selectedTag ? ['implications', selectedTag.id] : null,
    () => api.tags.listImplications({ tag_id: selectedTag!.id }),
  )

  const [aliasNs, setAliasNs] = useState('')
  const [aliasName, setAliasName] = useState('')

  const handleAddAlias = useCallback(async () => {
    if (!selectedTag || !aliasName.trim()) return
    try {
      await api.tags.createAlias(aliasNs || selectedTag.namespace, aliasName.trim(), selectedTag.id)
      setAliasNs('')
      setAliasName('')
      mutateAliases()
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [selectedTag, aliasNs, aliasName, mutateAliases])

  const handleDeleteAlias = useCallback(
    async (ns: string, name: string) => {
      try {
        await api.tags.deleteAlias(ns, name)
        mutateAliases()
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : String(e))
      }
    },
    [mutateAliases],
  )

  const [implTargetId, setImplTargetId] = useState('')
  const [implDirection, setImplDirection] = useState<'implies' | 'implied_by'>('implies')

  const handleAddImplication = useCallback(async () => {
    if (!selectedTag || !implTargetId) return
    const targetId = parseInt(implTargetId)
    if (isNaN(targetId)) return
    try {
      if (implDirection === 'implies') {
        await api.tags.createImplication(selectedTag.id, targetId)
      } else {
        await api.tags.createImplication(targetId, selectedTag.id)
      }
      setImplTargetId('')
      mutateImplications()
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [selectedTag, implTargetId, implDirection, mutateImplications])

  const handleDeleteImplication = useCallback(
    async (antId: number, conId: number) => {
      try {
        await api.tags.deleteImplication(antId, conId)
        mutateImplications()
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : String(e))
      }
    },
    [mutateImplications],
  )

  const totalPages = tagData?.total !== undefined ? Math.ceil(tagData.total / limit) : 0

  return (
    <div className="min-h-screen">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6">{t('tags.title')}</h1>

        {/* Filters */}
        <div className="mb-6 flex gap-3 flex-wrap">
          <input
            type="text"
            placeholder={t('tags.searchPlaceholder')}
            className="px-3 py-2 w-64 bg-vault-input border border-vault-border rounded-lg text-vault-text placeholder-vault-text-muted outline-none focus:border-vault-border-hover text-sm"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              resetTagPagination()
            }}
          />
          <input
            type="text"
            placeholder={t('tags.namespacePlaceholder')}
            className="px-3 py-2 w-48 bg-vault-input border border-vault-border rounded-lg text-vault-text placeholder-vault-text-muted outline-none focus:border-vault-border-hover text-sm"
            value={nsFilter}
            onChange={(e) => {
              setNsFilter(e.target.value)
              resetTagPagination()
            }}
          />
        </div>

        <div className="flex gap-6 flex-col lg:flex-row">
          {/* Tag table */}
          <div className="flex-1">
            <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
              <table className="w-full text-left">
                <thead className="bg-vault-card-hover">
                  <tr>
                    <th className="p-3 text-sm text-vault-text-muted font-medium">
                      {t('tags.id')}
                    </th>
                    <th className="p-3 text-sm text-vault-text-muted font-medium">
                      {t('tags.namespace')}
                    </th>
                    <th className="p-3 text-sm text-vault-text-muted font-medium">
                      {t('tags.name')}
                    </th>
                    <th className="p-3 text-sm text-vault-text-muted font-medium">
                      {t('tags.count')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {tagData?.tags.map((tag) => (
                    <tr
                      key={tag.id}
                      className={`border-t border-vault-border cursor-pointer transition-colors ${
                        selectedTag?.id === tag.id
                          ? 'bg-vault-accent/10'
                          : 'hover:bg-vault-card-hover'
                      }`}
                      onClick={() => setSelectedTag(tag)}
                    >
                      <td className="p-3 text-vault-text-muted text-sm">{tag.id}</td>
                      <td className="p-3 text-vault-text-secondary text-sm">{tag.namespace}</td>
                      <td className="p-3 font-mono text-vault-accent">{tag.name}</td>
                      <td className="p-3 text-sm">{tag.count}</td>
                    </tr>
                  ))}
                  {tagData?.tags.length === 0 && (
                    <tr>
                      <td className="p-4 text-vault-text-muted" colSpan={4}>
                        {t('tags.noTags')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Cursor-based pagination */}
            {isCursorMode && (hasPrevTag || hasNextTag) && (
              <div className="flex gap-2 mt-4 items-center">
                <button
                  type="button"
                  onClick={handlePrevTagCursor}
                  disabled={!hasPrevTag}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-vault-card border border-vault-border hover:bg-vault-card-hover disabled:opacity-30 text-sm transition-colors"
                >
                  <ChevronLeft size={14} /> {t('tags.prev')}
                </button>
                <button
                  type="button"
                  onClick={handleNextTagCursor}
                  disabled={!hasNextTag}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-vault-card border border-vault-border hover:bg-vault-card-hover disabled:opacity-30 text-sm transition-colors"
                >
                  {t('tags.next')} <ChevronRight size={14} />
                </button>
              </div>
            )}

            {/* Page-based pagination (offset mode) */}
            {!isCursorMode && totalPages > 1 && (
              <div className="flex gap-2 mt-4 items-center">
                <button
                  type="button"
                  onClick={() => setPage(Math.max(0, page - 1))}
                  disabled={page === 0}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-vault-card border border-vault-border hover:bg-vault-card-hover disabled:opacity-30 text-sm transition-colors"
                >
                  <ChevronLeft size={14} /> {t('tags.prev')}
                </button>
                <span className="text-sm text-vault-text-secondary">
                  {page + 1} / {totalPages} ({tagData?.total} tags)
                </span>
                <button
                  type="button"
                  onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                  disabled={page >= totalPages - 1}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-vault-card border border-vault-border hover:bg-vault-card-hover disabled:opacity-30 text-sm transition-colors"
                >
                  {t('tags.next')} <ChevronRight size={14} />
                </button>
              </div>
            )}
          </div>

          {/* Detail panel */}
          {selectedTag && (
            <div className="w-full lg:w-96 space-y-4">
              <div className="bg-vault-card border border-vault-border rounded-xl p-4">
                <h2 className="text-lg font-semibold mb-2">
                  <span className="text-vault-text-secondary">{selectedTag.namespace}:</span>
                  {selectedTag.name}
                </h2>
                <p className="text-sm text-vault-text-muted">
                  {t('tags.id')}: {selectedTag.id} | {t('tags.count')}: {selectedTag.count}
                </p>
              </div>

              {/* Aliases */}
              <div className="bg-vault-card border border-vault-border rounded-xl p-4">
                <h3 className="text-md font-semibold mb-3">{t('tags.aliases')}</h3>
                {aliases && aliases.length > 0 ? (
                  <ul className="space-y-1 mb-3">
                    {aliases.map((a) => (
                      <li
                        key={`${a.alias_namespace}:${a.alias_name}`}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="font-mono">
                          <span className="text-vault-text-muted">{a.alias_namespace}:</span>
                          {a.alias_name}
                        </span>
                        <button
                          onClick={() => handleDeleteAlias(a.alias_namespace, a.alias_name)}
                          className="p-1 text-red-400 hover:bg-red-500/10 rounded transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-vault-text-muted mb-3">{t('tags.noAliases')}</p>
                )}
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder={t('tags.namespacePlaceholder')}
                    className="p-2 w-16 bg-vault-input border border-vault-border rounded text-sm outline-none text-vault-text"
                    value={aliasNs}
                    onChange={(e) => setAliasNs(e.target.value)}
                  />
                  <input
                    type="text"
                    placeholder={t('tags.aliasNamePlaceholder')}
                    className="p-2 flex-1 bg-vault-input border border-vault-border rounded text-sm outline-none text-vault-text"
                    value={aliasName}
                    onChange={(e) => setAliasName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddAlias()}
                  />
                  <button
                    onClick={handleAddAlias}
                    className="flex items-center gap-1 px-3 py-2 bg-vault-accent hover:bg-vault-accent/90 rounded text-white text-sm font-medium transition-colors"
                  >
                    <Plus size={14} /> {t('tags.add')}
                  </button>
                </div>
              </div>

              {/* Implications */}
              <div className="bg-vault-card border border-vault-border rounded-xl p-4">
                <h3 className="text-md font-semibold mb-3">{t('tags.implications')}</h3>
                {implications && implications.length > 0 ? (
                  <ul className="space-y-1 mb-3">
                    {implications.map((imp) => (
                      <li
                        key={`${imp.antecedent_id}-${imp.consequent_id}`}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="font-mono">
                          <span className="text-orange-400">{imp.antecedent}</span>
                          <span className="text-vault-text-muted mx-1">&rarr;</span>
                          <span className="text-green-400">{imp.consequent}</span>
                        </span>
                        <button
                          onClick={() =>
                            handleDeleteImplication(imp.antecedent_id, imp.consequent_id)
                          }
                          className="p-1 text-red-400 hover:bg-red-500/10 rounded transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-vault-text-muted mb-3">{t('tags.noImplications')}</p>
                )}
                <div className="flex gap-2">
                  <select
                    className="p-2 bg-vault-input border border-vault-border rounded text-sm outline-none text-vault-text"
                    value={implDirection}
                    onChange={(e) => setImplDirection(e.target.value as 'implies' | 'implied_by')}
                  >
                    <option value="implies">{t('tags.implies')} &rarr;</option>
                    <option value="implied_by">&larr; {t('tags.impliedBy')}</option>
                  </select>
                  <input
                    type="number"
                    placeholder={t('tags.targetTagId')}
                    className="p-2 flex-1 bg-vault-input border border-vault-border rounded text-sm outline-none text-vault-text"
                    value={implTargetId}
                    onChange={(e) => setImplTargetId(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddImplication()}
                  />
                  <button
                    onClick={handleAddImplication}
                    className="flex items-center gap-1 px-3 py-2 bg-vault-accent hover:bg-vault-accent/90 rounded text-white text-sm font-medium transition-colors"
                  >
                    <Plus size={14} /> {t('tags.add')}
                  </button>
                </div>
              </div>
            </div>
          )}

          {!selectedTag && (
            <div className="w-full lg:w-96">
              <EmptyState icon={Tags} title={t('tags.selectTag')} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
