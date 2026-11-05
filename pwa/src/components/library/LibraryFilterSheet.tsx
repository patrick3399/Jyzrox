'use client'

import { useState } from 'react'
import { ChevronDown, HelpCircle } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { formatNumber, t } from '@/lib/i18n'
import { resolveCategoryColors } from '@/lib/categoryPalette'
import type { FacetKey, FacetSelection } from '@/lib/queryParser'
import type { GalleryCategoryDef } from '@/lib/types'
import { LibrarySyntaxHelpLines } from './LibrarySyntaxHelp'
import {
  FacetModeToggle,
  LibraryFacetList,
  facetSelectionLabel,
  useFacetModeDraft,
  visibleFacetOptions,
  type FacetOption,
} from './LibraryFacetList'

interface SelectOption {
  value: string | number
  label: string
}

interface LibraryFilterSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  categoryOptions: FacetOption[]
  sourceOptions: FacetOption[]
  categorySelection: FacetSelection
  sourceSelection: FacetSelection
  onFacetChange: (key: FacetKey, selection: FacetSelection) => void
  categoryDefs?: GalleryCategoryDef[]
  rating: number | null
  onRatingChange: (value: string | null) => void
  collection: number | null
  collections: SelectOption[]
  onCollectionChange: (value: string | null) => void
  sort: string
  sortOptions: SelectOption[]
  onSortChange: (value: string | null) => void
  /** Drops every filter but keeps the typed search text. */
  onReset: () => void
  /** Result count of the current query; null while unknown. */
  total: number | null
}

const SELECT =
  'w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text focus:outline-none'
const SECTION_LABEL = 'mb-2 block text-xs uppercase tracking-wide text-vault-text-muted'

/** Phone filter sheet: all library filters in one bottom sheet. Loaded on first open. */
export function LibraryFilterSheet({
  open,
  onOpenChange,
  categoryOptions,
  sourceOptions,
  categorySelection: committedCategorySelection,
  sourceSelection,
  onFacetChange,
  categoryDefs,
  rating,
  onRatingChange,
  collection,
  collections,
  onCollectionChange,
  sort,
  sortOptions,
  onSortChange,
  onReset,
  total,
}: LibraryFilterSheetProps) {
  const [sourceExpanded, setSourceExpanded] = useState(false)
  const [syntaxHelpOpen, setSyntaxHelpOpen] = useState(false)
  const [categorySelection, setCategoryMode] = useFacetModeDraft(
    committedCategorySelection,
    (selection) => onFacetChange('category', selection),
  )
  const selectedCategories = new Set(categorySelection.values)
  const visibleCategories = visibleFacetOptions(categoryOptions, categorySelection)
  const sourceSummary =
    facetSelectionLabel(
      sourceSelection,
      (value) => sourceOptions.find((o) => o.value === value)?.label ?? value,
    ) ?? t('library.allSources')

  const toggleCategory = (value: string) => {
    const values = selectedCategories.has(value)
      ? categorySelection.values.filter((v) => v !== value)
      : [...categorySelection.values, value]
    onFacetChange('category', { mode: categorySelection.mode, values })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('library.filters')}
      footer={
        <>
          <Button variant="secondary" onClick={onReset}>
            {t('library.resetFilters')}
          </Button>
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            {total === null ? t('common.done') : t('library.showResults', { count: formatNumber(total) })}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <section>
          <span className={SECTION_LABEL}>{t('library.filterCategory')}</span>
          <div className="space-y-3">
            <FacetModeToggle mode={categorySelection.mode} onChange={setCategoryMode} />
            <div className="flex flex-wrap gap-2">
              {visibleCategories.map((option) => {
                const checked = selectedCategories.has(option.value)
                const colors = resolveCategoryColors(option.colorKey ?? option.label, categoryDefs)
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={checked}
                    onClick={() => toggleCategory(option.value)}
                    className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
                      checked
                        ? `${colors.badge} border-transparent text-white`
                        : 'border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover'
                    }`}
                  >
                    {!checked && (
                      <span
                        aria-hidden="true"
                        className={`size-2 rounded-full ${colors.swatch}`}
                      />
                    )}
                    <span>{option.label}</span>
                    <span className={checked ? 'text-white/80' : 'text-vault-text-muted'}>
                      {formatNumber(option.count)}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        </section>

        <section>
          <span className={SECTION_LABEL}>{t('library.source')}</span>
          <button
            type="button"
            aria-expanded={sourceExpanded}
            onClick={() => setSourceExpanded((v) => !v)}
            className="flex w-full items-center justify-between gap-2 rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text"
          >
            <span className="truncate">{sourceSummary}</span>
            <ChevronDown
              size={16}
              className={`shrink-0 transition-transform ${sourceExpanded ? 'rotate-180' : ''}`}
            />
          </button>
          {sourceExpanded && (
            <div className="mt-3">
              <LibraryFacetList
                options={sourceOptions}
                selection={sourceSelection}
                onChange={(selection) => onFacetChange('source', selection)}
              />
            </div>
          )}
        </section>

        <section>
          <label className={SECTION_LABEL} htmlFor="library-sheet-rating">
            {t('library.minRating')}
          </label>
          <select
            id="library-sheet-rating"
            value={rating ?? ''}
            onChange={(e) => onRatingChange(e.target.value || null)}
            className={SELECT}
          >
            <option value="">{t('library.any')}</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}+
              </option>
            ))}
          </select>
        </section>

        {collections.length > 0 && (
          <section>
            <label className={SECTION_LABEL} htmlFor="library-sheet-collection">
              {t('collections.filterByCollection')}
            </label>
            <select
              id="library-sheet-collection"
              value={collection ?? ''}
              onChange={(e) => onCollectionChange(e.target.value || null)}
              className={SELECT}
            >
              <option value="">{t('collections.allCollections')}</option>
              {collections.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </section>
        )}

        <section>
          <label className={SECTION_LABEL} htmlFor="library-sheet-sort">
            {t('library.sort')}
          </label>
          <select
            id="library-sheet-sort"
            value={sort}
            onChange={(e) =>
              onSortChange(e.target.value === 'added_at' ? null : e.target.value || null)
            }
            className={SELECT}
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </section>

        <section>
          <button
            type="button"
            onClick={() => setSyntaxHelpOpen((v) => !v)}
            aria-expanded={syntaxHelpOpen}
            className={`flex items-center gap-1 text-sm transition-colors ${
              syntaxHelpOpen ? 'text-vault-accent' : 'text-vault-text-muted hover:text-vault-accent'
            }`}
          >
            <HelpCircle size={16} />
            {t('library.syntaxHelp')}
          </button>
          {syntaxHelpOpen && <LibrarySyntaxHelpLines />}
        </section>
      </div>
    </Dialog>
  )
}
