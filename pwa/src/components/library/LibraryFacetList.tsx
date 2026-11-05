'use client'

import { useState } from 'react'
import { Search } from 'lucide-react'
import { formatNumber, t } from '@/lib/i18n'
import { resolveCategoryColors } from '@/lib/categoryPalette'
import type { FacetMode, FacetSelection } from '@/lib/queryParser'
import type { GalleryCategoryDef } from '@/lib/types'

export interface FacetOption {
  value: string
  label: string
  count: number
  /** Category name; when set the row shows that category's colour swatch. */
  colorKey?: string
}

/** Past this many visible options the list gets a filter input. */
export const FACET_FILTER_THRESHOLD = 8
/** The desktop grid shows this many at a glance, so its filter input comes later. */
export const FACET_GRID_FILTER_THRESHOLD = 24

export type FacetColumns = 1 | 2 | 3

/**
 * Desktop popover columns: every option fits without scrolling while the list
 * is short, and the grid widens before it gets tall as sources/categories grow.
 */
export function facetGridColumns(visibleCount: number): FacetColumns {
  if (visibleCount <= 6) return 1
  if (visibleCount <= 20) return 2
  return 3
}

// Full class names so Tailwind's source scan sees them.
const GRID_COLUMNS: Record<FacetColumns, string> = {
  1: 'space-y-0.5',
  2: 'grid grid-cols-2 gap-x-2 gap-y-0.5',
  3: 'grid grid-cols-3 gap-x-2 gap-y-0.5',
}

/** Options shown for a selection: non-empty ones, plus every selected value even if unknown or empty. */
export function visibleFacetOptions(options: FacetOption[], selection: FacetSelection): FacetOption[] {
  const selected = new Set(selection.values)
  const known = new Set(options.map((option) => option.value))
  const missing = selection.values
    .filter((value) => !known.has(value))
    .map((value) => ({ value, label: value, count: 0 }))
  return [...options.filter((option) => option.count > 0 || selected.has(option.value)), ...missing]
}

/** Button/summary text: "A", "A +2", or "Not: A +2" in exclude mode. Null when nothing is selected. */
export function facetSelectionLabel(
  selection: FacetSelection,
  labelOf: (value: string) => string,
): string | null {
  const [first, ...rest] = selection.values
  if (first === undefined) return null
  const shown =
    rest.length > 0
      ? t('library.facetMore', { label: labelOf(first), count: rest.length })
      : labelOf(first)
  return selection.mode === 'exclude' ? t('library.facetNot', { value: shown }) : shown
}

/**
 * An empty facet records no mode in the query, so "All except" with nothing
 * checked would snap back to "Only these". Keep the chosen mode in a draft
 * until the first value lands; once values exist the selection is the truth.
 */
export function useFacetModeDraft(
  selection: FacetSelection,
  onChange: (selection: FacetSelection) => void,
): [FacetSelection, (mode: FacetMode) => void] {
  const [draft, setDraft] = useState<FacetMode | null>(null)
  const effective: FacetSelection =
    selection.values.length > 0 ? selection : { mode: draft ?? selection.mode, values: [] }
  const setMode = (mode: FacetMode) => {
    setDraft(mode)
    if (selection.values.length > 0) onChange({ mode, values: selection.values })
  }
  return [effective, setMode]
}

const SEGMENT =
  'flex-1 px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap'

/** "Only these" / "All except" segmented control. */
export function FacetModeToggle({
  mode,
  onChange,
}: {
  mode: FacetMode
  onChange: (mode: FacetMode) => void
}) {
  return (
    <div
      role="radiogroup"
      aria-label={t('library.facetMode')}
      className="flex overflow-hidden rounded-lg border border-vault-border"
    >
      {(['include', 'exclude'] as const).map((value) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={mode === value}
          onClick={() => onChange(value)}
          className={`${SEGMENT} ${
            mode === value
              ? 'bg-vault-accent/10 text-vault-accent'
              : 'text-vault-text-secondary hover:text-vault-text'
          }`}
        >
          {value === 'include' ? t('library.facetOnly') : t('library.facetExcept')}
        </button>
      ))}
    </div>
  )
}

interface LibraryFacetListProps {
  options: FacetOption[]
  selection: FacetSelection
  onChange: (selection: FacetSelection) => void
  categoryDefs?: GalleryCategoryDef[]
  /** Desktop popover grid; the mobile sheet keeps the single scrolling column. */
  columns?: FacetColumns
}

/** Mode toggle plus a checkbox list with counts; shared by the desktop popover and the mobile sheet. */
export function LibraryFacetList({
  options,
  selection: committed,
  onChange,
  categoryDefs,
  columns,
}: LibraryFacetListProps) {
  const grid = columns !== undefined
  const filterThreshold = grid ? FACET_GRID_FILTER_THRESHOLD : FACET_FILTER_THRESHOLD
  const [selection, setMode] = useFacetModeDraft(committed, onChange)
  const [filter, setFilter] = useState('')
  const visible = visibleFacetOptions(options, selection)
  const needle = filter.trim().toLowerCase()
  const shown = needle
    ? visible.filter((option) => option.label.toLowerCase().includes(needle))
    : visible

  const toggle = (value: string, checked: boolean) => {
    const values = checked
      ? [...selection.values.filter((v) => v !== value), value]
      : selection.values.filter((v) => v !== value)
    onChange({ mode: selection.mode, values })
  }

  return (
    <div className="space-y-3">
      <FacetModeToggle mode={selection.mode} onChange={setMode} />
      {visible.length > filterThreshold && (
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-vault-text-muted"
          />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('library.facetFilterPlaceholder')}
            aria-label={t('library.facetFilterPlaceholder')}
            className="w-full rounded-lg border border-vault-border bg-vault-input py-1.5 pl-8 pr-2 text-sm text-vault-text placeholder-vault-text-muted focus:border-vault-border-hover focus:outline-none"
          />
        </div>
      )}
      <ul
        data-testid="facet-options"
        data-columns={columns ?? 1}
        className={`overflow-y-auto ${
          grid ? `max-h-[min(60vh,36rem)] ${GRID_COLUMNS[columns]}` : 'max-h-64 space-y-0.5'
        }`}
      >
        {shown.map((option) => {
          const checked = selection.values.includes(option.value)
          return (
            <li key={option.value}>
              <label className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-vault-text hover:bg-vault-card-hover">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => toggle(option.value, e.target.checked)}
                  className="size-4 shrink-0 accent-vault-accent"
                />
                {option.colorKey !== undefined && (
                  <span
                    aria-hidden="true"
                    data-testid="facet-swatch"
                    className={`size-2.5 shrink-0 rounded-full ${resolveCategoryColors(option.colorKey, categoryDefs).swatch}`}
                  />
                )}
                <span className="min-w-0 flex-1 truncate">{option.label}</span>
                <span className="shrink-0 text-xs tabular-nums text-vault-text-muted">
                  {formatNumber(option.count)}
                </span>
              </label>
            </li>
          )
        })}
        {shown.length === 0 && (
          <li className="col-span-full px-2 py-1.5 text-sm text-vault-text-muted">
            {t('library.facetNoMatches')}
          </li>
        )}
      </ul>
    </div>
  )
}
