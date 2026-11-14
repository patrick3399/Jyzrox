'use client'

import type { ReactNode } from 'react'
import { Check, HelpCircle, RotateCcw } from 'lucide-react'
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

export type LibraryFilterSection = 'category' | 'source' | 'rating' | 'collection' | 'sort' | 'help'

interface SelectOption {
  value: string | number
  label: string
}

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
  /** Drops every filter but keeps the typed search text. */
  onReset: () => void
  /** Shows the Reset pill. */
  hasActiveFilters: boolean
}

const PILL =
  'flex h-8 shrink-0 max-w-48 items-center gap-1 rounded-full border px-2.5 text-sm transition-colors'
// No chevron: the pill row has to fit a phone width, so colour alone marks a
// pill as set or expanded (aria-expanded carries it for assistive tech).
const PILL_ACTIVE = 'border-vault-accent bg-vault-accent/10 text-vault-accent'
const PILL_IDLE =
  'border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text'
const OPTION_ROW =
  'flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-vault-card-hover'

const SECTION_ID = 'library-filter-section'

// A pointer press must not move focus into the search block: focus there keeps
// the block revealed, and scrolling the results is what collapses the section.
const keepFocus = (e: React.MouseEvent) => e.preventDefault()

function Pill({
  section,
  current,
  active,
  onToggle,
  children,
}: {
  section: LibraryFilterSection
  current: LibraryFilterSection | null
  active: boolean
  onToggle: (section: LibraryFilterSection) => void
  children: ReactNode
}) {
  const expanded = current === section
  return (
    <button
      type="button"
      data-section={section}
      aria-expanded={expanded}
      aria-controls={expanded ? SECTION_ID : undefined}
      onMouseDown={keepFocus}
      onClick={() => onToggle(section)}
      className={`${PILL} ${active || expanded ? PILL_ACTIVE : PILL_IDLE}`}
    >
      <span className="truncate">{children}</span>
    </button>
  )
}

/** Single-choice rows; picking one closes the section. */
function OptionRows({
  options,
  value,
  onPick,
}: {
  options: SelectOption[]
  value: string | number
  onPick: (value: string | number) => void
}) {
  return (
    <ul role="radiogroup" className="space-y-0.5">
      {options.map((option) => {
        const checked = option.value === value
        return (
          <li key={option.value}>
            <button
              type="button"
              role="radio"
              aria-checked={checked}
              onMouseDown={keepFocus}
              onClick={() => onPick(option.value)}
              className={`${OPTION_ROW} ${checked ? 'text-vault-accent' : 'text-vault-text'}`}
            >
              <span className="min-w-0 truncate">{option.label}</span>
              {checked && <Check size={16} className="shrink-0" />}
            </button>
          </li>
        )
      })}
    </ul>
  )
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
  const sortActive = sort !== 'added_at'
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
          {rating === null ? t('library.minRating') : `${t('library.minRating')} ${rating}+`}
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
          {sortActive && sortLabel ? `${t('library.sort')} · ${sortLabel}` : t('library.sort')}
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
            <OptionRows
              options={sortOptions}
              value={sort}
              onPick={(value) => {
                onSortChange(value === 'added_at' ? null : String(value))
                onSectionChange(null)
              }}
            />
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
