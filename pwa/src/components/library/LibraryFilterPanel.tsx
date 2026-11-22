'use client'

import { HelpCircle, RotateCcw } from 'lucide-react'
import { formatNumber, t } from '@/lib/i18n'
import { resolveCategoryColors } from '@/lib/categoryPalette'
import { defaultSortDirection, type FacetKey, type FacetSelection } from '@/lib/queryParser'
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
import {
  OptionRows,
  PILL,
  PILL_ACTIVE,
  PILL_IDLE,
  Pill,
  SECTION_ID,
  keepFocus,
  type LibraryFilterSection,
  type SelectOption,
} from './LibraryFilterParts'

export type { LibraryFilterSection }

interface LibraryFilterPanelProps {
  /** The section expanded under the pill row; null shows the pill row alone. */
  section: LibraryFilterSection | null
  onSectionChange: (section: LibraryFilterSection | null) => void
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
  /** Effective direction of the current sort. */
  sortDirection: 'asc' | 'desc'
  onSortDirectionToggle: () => void
  /** Drops every filter but keeps the typed search text. */
  onReset: () => void
  /** Shows the Reset pill. */
  hasActiveFilters: boolean
}

/**
 * Phone/tablet filters, inline under the search row: one scrolling row of
 * pills that each show their current value, and the tapped pill's options
 * expanded in place below. Results stay visible and update as filters change.
 */
export function LibraryFilterPanel({
  section,
  onSectionChange,
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
  sortDirection,
  onSortDirectionToggle,
  onReset,
  hasActiveFilters,
}: LibraryFilterPanelProps) {
  const [categorySelection, setCategoryMode] = useFacetModeDraft(
    committedCategorySelection,
    (selection) => onFacetChange('category', selection),
  )
  const selectedCategories = new Set(categorySelection.values)
  const toggle = (next: LibraryFilterSection) => onSectionChange(section === next ? null : next)

  const labelOf = (options: FacetOption[]) => (value: string) =>
    options.find((o) => o.value === value)?.label ?? value
  const categoryText =
    facetSelectionLabel(committedCategorySelection, labelOf(categoryOptions)) ??
    t('library.filterCategory')
  const sourceText =
    facetSelectionLabel(sourceSelection, labelOf(sourceOptions)) ?? t('library.source')
  const collectionText =
    collections.find((c) => c.value === collection)?.label ?? t('collections.filterByCollection')
  const sortActive = sort !== 'added_at' || sortDirection !== defaultSortDirection(sort)
  const sortLabel = sortOptions.find((o) => o.value === sort)?.label

  const toggleCategory = (value: string) => {
    const values = selectedCategories.has(value)
      ? categorySelection.values.filter((v) => v !== value)
      : [...categorySelection.values, value]
    onFacetChange('category', { mode: categorySelection.mode, values })
  }

  return (
    <div className="mt-2">
      <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <Pill
          section="category"
          current={section}
          active={committedCategorySelection.values.length > 0}
          onToggle={toggle}
        >
          {categoryText}
        </Pill>
        <Pill
          section="source"
          current={section}
          active={sourceSelection.values.length > 0}
          onToggle={toggle}
        >
          {sourceText}
        </Pill>
        <Pill section="rating" current={section} active={rating !== null} onToggle={toggle}>
          {rating === null ? t('library.rating') : `${t('library.rating')} ${rating}+`}
        </Pill>
        {collections.length > 0 && (
          <Pill
            section="collection"
            current={section}
            active={collection !== null}
            onToggle={toggle}
          >
            {collectionText}
          </Pill>
        )}
        <Pill section="sort" current={section} active={sortActive} onToggle={toggle}>
          {sortActive && sortLabel
            ? `${t('library.sort')} · ${sortLabel} ${sortDirection === 'asc' ? '↑' : '↓'}`
            : t('library.sort')}
        </Pill>
        {hasActiveFilters && (
          <button
            type="button"
            onMouseDown={keepFocus}
            onClick={onReset}
            className={`${PILL} ${PILL_IDLE}`}
          >
            <RotateCcw size={14} className="shrink-0" />
            {t('library.resetFilters')}
          </button>
        )}
        <button
          type="button"
          data-section="help"
          aria-expanded={section === 'help'}
          aria-controls={section === 'help' ? SECTION_ID : undefined}
          aria-label={t('library.syntaxHelp')}
          title={t('library.syntaxHelp')}
          onMouseDown={keepFocus}
          onClick={() => toggle('help')}
          className={`${PILL} ${section === 'help' ? PILL_ACTIVE : PILL_IDLE}`}
        >
          <HelpCircle size={16} className="shrink-0" />
        </button>
      </div>

      {section !== null && (
        <div
          id={SECTION_ID}
          data-testid="library-filter-section"
          className="mt-2 max-h-[40vh] overflow-y-auto overscroll-contain rounded-lg border border-vault-border bg-vault-card p-3"
        >
          {section === 'category' && (
            <div className="space-y-3">
              <FacetModeToggle mode={categorySelection.mode} onChange={setCategoryMode} />
              <div className="flex flex-wrap gap-2">
                {visibleFacetOptions(categoryOptions, categorySelection).map((option) => {
                  const checked = selectedCategories.has(option.value)
                  const colors = resolveCategoryColors(
                    option.colorKey ?? option.label,
                    categoryDefs,
                  )
                  return (
                    <button
                      key={option.value}
                      type="button"
                      aria-pressed={checked}
                      onMouseDown={keepFocus}
                      onClick={() => toggleCategory(option.value)}
                      className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors ${
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
          )}

          {section === 'source' && (
            <LibraryFacetList
              options={sourceOptions}
              selection={sourceSelection}
              onChange={(selection) => onFacetChange('source', selection)}
            />
          )}

          {section === 'rating' && (
            <div
              role="radiogroup"
              aria-label={t('library.minRating')}
              className="flex overflow-hidden rounded-lg border border-vault-border"
            >
              {[null, 1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n ?? 'any'}
                  type="button"
                  role="radio"
                  aria-checked={rating === n}
                  onMouseDown={keepFocus}
                  onClick={() => {
                    onRatingChange(n === null ? null : String(n))
                    onSectionChange(null)
                  }}
                  className={`flex-1 py-2 text-sm font-medium transition-colors ${
                    rating === n
                      ? 'bg-vault-accent/10 text-vault-accent'
                      : 'text-vault-text-secondary hover:text-vault-text'
                  }`}
                >
                  {n === null ? t('library.any') : `${n}+`}
                </button>
              ))}
            </div>
          )}

          {section === 'collection' && (
            <OptionRows
              options={[{ value: '', label: t('collections.allCollections') }, ...collections]}
              value={collection ?? ''}
              onPick={(value) => {
                onCollectionChange(value === '' ? null : String(value))
                onSectionChange(null)
              }}
            />
          )}

          {section === 'sort' && (
            <>
              <button
                type="button"
                data-testid="library-sort-direction"
                aria-label={t('library.sortDirection')}
                onMouseDown={keepFocus}
                onClick={onSortDirectionToggle}
                className={`${PILL} ${PILL_IDLE} mb-2`}
              >
                {sortDirection === 'asc'
                  ? `↑ ${t('library.sortAscending')}`
                  : `↓ ${t('library.sortDescending')}`}
              </button>
              <OptionRows
                options={sortOptions}
                value={sort}
                onPick={(value) => {
                  onSortChange(value === 'added_at' ? null : String(value))
                  onSectionChange(null)
                }}
              />
            </>
          )}

          {section === 'help' && (
            // The cheat sheet brings its own top margin for the desktop panel.
            <div className="-mt-4">
              <LibrarySyntaxHelpLines />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
