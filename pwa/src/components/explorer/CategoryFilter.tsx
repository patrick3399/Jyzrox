'use client'

import { useMemo } from 'react'
import { useCategoryRegistry } from '@/hooks/useCategoryRegistry'
import { t } from '@/lib/i18n'

export const UNCATEGORIZED_FILTER = '__uncategorized__'

interface CategoryFilterProps {
  value: string | null
  counts?: Record<string, number>
  onChange: (value: string | null) => void
}

export function CategoryFilter({ value, counts, onChange }: CategoryFilterProps) {
  const { data: registry } = useCategoryRegistry()

  const names = useMemo(() => {
    const registered = [...(registry?.categories ?? [])]
      .sort((a, b) => a.sort_order - b.sort_order)
      .map((category) => category.name)
    const known = new Set(registered)
    const extra = Object.keys(counts ?? {}).filter((key) => key !== UNCATEGORIZED_FILTER && !known.has(key))
    if (value && value !== UNCATEGORIZED_FILTER && !known.has(value) && !extra.includes(value)) extra.push(value)
    return [...registered, ...extra]
  }, [registry?.categories, counts, value])

  const label = (text: string, key: string) => {
    const count = counts?.[key]
    return count === undefined ? text : `${text} (${count})`
  }

  return (
    <select
      aria-label={t('explorer.filterCategory')}
      data-testid="category-filter"
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value || null)}
      className="rounded-md border border-vault-border bg-vault-bg px-2 py-1 text-xs text-vault-text"
    >
      <option value="">{t('explorer.allCategories')}</option>
      <option value={UNCATEGORIZED_FILTER}>{label(t('explorer.uncategorized'), UNCATEGORIZED_FILTER)}</option>
      {names.map((name) => (
        <option key={name} value={name} className={counts && !counts[name] ? 'text-vault-text-muted' : undefined}>
          {label(name, name)}
        </option>
      ))}
    </select>
  )
}
