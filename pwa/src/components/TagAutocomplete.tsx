'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { TagItem } from '@/lib/types'

interface TagAutocompleteProps {
  /** Called when a tag is selected */
  onSelect: (tag: string) => void
  /** Placeholder text */
  placeholder?: string
  /** Input className override */
  className?: string
  /** Clear input after selection */
  clearOnSelect?: boolean
  /** Allow multiple selections (comma-joined) */
  multiple?: boolean
  /** Initial value */
  value?: string
  /** Controlled onChange for multiple mode */
  onChange?: (value: string) => void
}

export function TagAutocomplete({
  onSelect,
  placeholder,
  className,
  clearOnSelect = true,
  multiple = false,
  value,
  onChange,
}: TagAutocompleteProps) {
  const [query, setQuery] = useState(value ?? '')
  const [suggestions, setSuggestions] = useState<TagItem[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Sync controlled value
  useEffect(() => {
    if (value !== undefined) setQuery(value)
  }, [value])

  // Debounced autocomplete fetch
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const trimmed = query.trim()
    if (!trimmed) {
      setSuggestions([])
      setOpen(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const results = await api.tags.autocomplete(trimmed, 10)
        setSuggestions(results)
        setOpen(results.length > 0)
        setHighlightIdx(-1)
      } catch {
        setSuggestions([])
        setOpen(false)
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleSelect = useCallback(
    (tag: TagItem) => {
      const tagStr = `${tag.namespace}:${tag.name}`
      onSelect(tagStr)
      if (clearOnSelect) {
        setQuery('')
        onChange?.('')
      } else {
        setQuery(tagStr)
        onChange?.(tagStr)
      }
      setSuggestions([])
      setOpen(false)
      setHighlightIdx(-1)
    },
    [onSelect, clearOnSelect, onChange],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (!open) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setHighlightIdx((i) => Math.min(i + 1, suggestions.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setHighlightIdx((i) => Math.max(i - 1, -1))
      } else if (e.key === 'Enter' && highlightIdx >= 0) {
        e.preventDefault()
        handleSelect(suggestions[highlightIdx])
      } else if (e.key === 'Escape') {
        setOpen(false)
        setHighlightIdx(-1)
      }
    },
    [open, suggestions, highlightIdx, handleSelect],
  )

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setQuery(e.target.value)
      onChange?.(e.target.value)
    },
    [onChange],
  )

  return (
    <div ref={containerRef} className="relative">
      <input
        type="text"
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        placeholder={placeholder ?? t('tag.autocomplete.placeholder')}
        className={
          className ??
          'w-full bg-vault-input border border-vault-border rounded px-3 py-1.5 text-sm text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors'
        }
        autoComplete="off"
        spellCheck={false}
      />

      {/* Loading indicator */}
      {loading && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2">
          <div className="w-3 h-3 border border-vault-text-muted border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {/* Dropdown */}
      {open && suggestions.length > 0 && (
        <ul className="absolute z-50 top-full left-0 right-0 mt-1 bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden max-h-60 overflow-y-auto">
          {suggestions.map((tag, idx) => (
            <li key={`${tag.namespace}:${tag.name}`}>
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault()
                  handleSelect(tag)
                }}
                onMouseEnter={() => setHighlightIdx(idx)}
                className={`w-full flex items-center justify-between px-3 py-2 text-left text-sm transition-colors ${
                  idx === highlightIdx
                    ? 'bg-vault-accent/10 text-vault-accent'
                    : 'text-vault-text hover:bg-vault-card-hover'
                }`}
              >
                <span className="min-w-0 truncate">
                  <span className="text-vault-text-muted text-xs">{tag.namespace}:</span>
                  <span className="font-medium">{tag.name}</span>
                  {tag.translation && (
                    <span className="text-vault-text-muted text-xs ml-1">
                      ({tag.translation})
                    </span>
                  )}
                </span>
                <span className="text-xs text-vault-text-muted ml-2 shrink-0">{tag.count}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* No results hint (only show if user typed something and got nothing) */}
      {open && suggestions.length === 0 && !loading && query.trim() && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-vault-card border border-vault-border rounded-lg shadow-xl px-3 py-2 text-sm text-vault-text-muted">
          {t('tag.autocomplete.noResults')}
        </div>
      )}
    </div>
  )
}
