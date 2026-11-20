'use client'

import type { ReactNode } from 'react'
import { Check } from 'lucide-react'

export type LibraryFilterSection = 'category' | 'source' | 'rating' | 'collection' | 'sort' | 'help'

export interface SelectOption {
  value: string | number
  label: string
}

export const PILL =
  'flex h-8 shrink-0 max-w-48 items-center gap-1 rounded-full border px-2.5 text-sm transition-colors'
// No chevron: the pill row has to fit a phone width, so colour alone marks a
// pill as set or expanded (aria-expanded carries it for assistive tech).
export const PILL_ACTIVE = 'border-vault-accent bg-vault-accent/10 text-vault-accent'
export const PILL_IDLE =
  'border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text'
const OPTION_ROW =
  'flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-vault-card-hover'

export const SECTION_ID = 'library-filter-section'

// A pointer press must not move focus into the search block: focus there keeps
// the block revealed, and scrolling the results is what collapses the section.
export const keepFocus = (e: React.MouseEvent) => e.preventDefault()

export function Pill({
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
export function OptionRows({
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
