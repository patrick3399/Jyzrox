'use client'

import { useRef, useState } from 'react'
import { Search, SlidersHorizontal, X } from 'lucide-react'
import { t } from '@/lib/i18n'

interface LibrarySearchBarProps {
  value: string
  onChange: (value: string) => void
  onCommit: (value: string) => void
  onClear: () => void
  onCancel: () => void
  activeFilterCount: number
  onOpenFilters: () => void
}

/**
 * One-row search: input + filter button. While the input is focused the filter
 * button collapses and a Cancel button takes its place.
 */
export function LibrarySearchBar({
  value,
  onChange,
  onCommit,
  onClear,
  onCancel,
  activeFilterCount,
  onOpenFilters,
}: LibrarySearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [focused, setFocused] = useState(false)

  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1 min-w-0">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-vault-text-muted pointer-events-none"
        />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              onCommit(value)
              inputRef.current?.blur()
            }
          }}
          placeholder={t('library.searchPlaceholder')}
          className="w-full bg-vault-input border border-vault-border rounded-lg pl-9 pr-10 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover text-sm"
        />
        {value && (
          <button
            type="button"
            onClick={onClear}
            className="absolute right-0 top-0 h-full w-10 flex items-center justify-center text-vault-text-muted hover:text-vault-text transition-colors"
            aria-label={t('browse.clearSearch')}
            title={t('browse.clearSearch')}
          >
            <X size={16} />
          </button>
        )}
      </div>

      <div
        className={`shrink-0 overflow-hidden transition-[max-width,opacity] duration-200 ${
          focused ? 'max-w-0 opacity-0' : 'max-w-12 opacity-100'
        }`}
        aria-hidden={focused || undefined}
      >
        <button
          type="button"
          onClick={onOpenFilters}
          tabIndex={focused ? -1 : undefined}
          aria-label={t('library.filters')}
          title={t('library.filters')}
          className="relative flex h-10 w-10 items-center justify-center rounded-lg border border-vault-border bg-vault-input text-vault-text-secondary hover:text-vault-text hover:border-vault-border-hover transition-colors"
        >
          <SlidersHorizontal size={16} />
          {activeFilterCount > 0 && (
            <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-vault-accent text-white text-[10px] leading-4 text-center">
              {activeFilterCount}
            </span>
          )}
        </button>
      </div>

      <div
        className={`shrink-0 overflow-hidden transition-[max-width,opacity] duration-200 ${
          focused ? 'max-w-24 opacity-100' : 'max-w-0 opacity-0'
        }`}
        aria-hidden={!focused || undefined}
      >
        <button
          type="button"
          tabIndex={focused ? undefined : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            onCancel()
            inputRef.current?.blur()
          }}
          className="px-2 py-2 whitespace-nowrap text-sm text-vault-text-secondary hover:text-vault-text transition-colors"
        >
          {t('common.cancel')}
        </button>
      </div>
    </div>
  )
}
