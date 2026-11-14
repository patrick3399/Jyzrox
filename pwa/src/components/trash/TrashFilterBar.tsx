'use client'

import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { t } from '@/lib/i18n'
import type { TrashReasonFilter, TrashSort, TrashSortDirection } from '@/lib/types'

export const TRASH_REASON_FILTERS: readonly TrashReasonFilter[] = [
  'user',
  'merged',
  'source_missing',
  'unknown',
]
export const TRASH_SORTS: readonly TrashSort[] = ['deleted_at', 'title', 'pages', 'size']

const SORT_LABEL_KEY: Record<TrashSort, string> = {
  deleted_at: 'trash.sortDeletedAt',
  title: 'trash.sortTitle',
  pages: 'trash.sortPages',
  size: 'trash.sortSize',
}

const SEARCH_DEBOUNCE_MS = 300

const CONTROL_CLASS =
  'min-w-0 px-2 py-1.5 text-xs bg-vault-input border border-vault-border rounded text-vault-text'

interface TrashFilterBarProps {
  q: string
  source: string
  reason: TrashReasonFilter | ''
  sort: TrashSort
  dir: TrashSortDirection
  sources: string[]
  onSearchChange: (q: string) => void
  onSourceChange: (source: string) => void
  onReasonChange: (reason: TrashReasonFilter | '') => void
  onSortChange: (sort: TrashSort) => void
  onDirChange: (dir: TrashSortDirection) => void
}

export function TrashFilterBar({
  q,
  source,
  reason,
  sort,
  dir,
  sources,
  onSearchChange,
  onSourceChange,
  onReasonChange,
  onSortChange,
  onDirChange,
}: TrashFilterBarProps) {
  const [text, setText] = useState(q)
  // Last value this bar pushed to the URL; lets us tell a foreign change
  // (clear filters, back/forward) from the echo of our own debounced update.
  const emittedRef = useRef(q)
  const onSearchRef = useRef(onSearchChange)
  useEffect(() => {
    onSearchRef.current = onSearchChange
  }, [onSearchChange])

  useEffect(() => {
    if (q !== emittedRef.current) {
      emittedRef.current = q
      setText(q)
    }
  }, [q])

  useEffect(() => {
    if (text === emittedRef.current) return
    const id = setTimeout(() => {
      emittedRef.current = text
      onSearchRef.current(text)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [text])

  // Keep a URL-selected source selectable even if it is no longer in the list.
  const sourceOptions = source && !sources.includes(source) ? [source, ...sources] : sources

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="trash-filter-bar">
      <div className="relative min-w-40 flex-1">
        <Search
          size={14}
          className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-vault-text-muted"
        />
        <input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('trash.searchPlaceholder')}
          aria-label={t('trash.searchPlaceholder')}
          data-testid="trash-search"
          className={`${CONTROL_CLASS} w-full pl-7`}
        />
      </div>
      <select
        value={source}
        onChange={(e) => onSourceChange(e.target.value)}
        aria-label={t('trash.filterSource')}
        data-testid="trash-filter-source"
        className={CONTROL_CLASS}
      >
        <option value="">{`${t('trash.filterSource')}: ${t('trash.filterAll')}`}</option>
        {sourceOptions.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <select
        value={reason}
        onChange={(e) => onReasonChange(e.target.value as TrashReasonFilter | '')}
        aria-label={t('trash.filterReason')}
        data-testid="trash-filter-reason"
        className={CONTROL_CLASS}
      >
        <option value="">{`${t('trash.filterReason')}: ${t('trash.filterAll')}`}</option>
        {TRASH_REASON_FILTERS.map((r) => (
          <option key={r} value={r}>
            {t(`trash.reason.${r}`)}
          </option>
        ))}
      </select>
      <select
        value={sort}
        onChange={(e) => onSortChange(e.target.value as TrashSort)}
        aria-label={t('trash.sort')}
        data-testid="trash-sort"
        className={CONTROL_CLASS}
      >
        {TRASH_SORTS.map((s) => (
          <option key={s} value={s}>
            {t(SORT_LABEL_KEY[s])}
          </option>
        ))}
      </select>
      <select
        value={dir}
        onChange={(e) => onDirChange(e.target.value as TrashSortDirection)}
        aria-label={t('trash.sort')}
        data-testid="trash-sort-dir"
        className={CONTROL_CLASS}
      >
        <option value="desc">{t('trash.sortDesc')}</option>
        <option value="asc">{t('trash.sortAsc')}</option>
      </select>
    </div>
  )
}
