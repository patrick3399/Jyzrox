import { useState, type KeyboardEvent } from 'react'
import { TagBadge } from './TagBadge'

interface TagInputProps {
  includeTags: string[]
  excludeTags: string[]
  onAddInclude: (tag: string) => void
  onRemoveInclude: (tag: string) => void
  onAddExclude: (tag: string) => void
  onRemoveExclude: (tag: string) => void
}

interface TagFieldProps {
  label: string
  tags: string[]
  variant: 'include' | 'exclude'
  placeholder: string
  onAdd: (tag: string) => void
  onRemove: (tag: string) => void
}

function TagField({ label, tags, variant, placeholder, onAdd, onRemove }: TagFieldProps) {
  const [inputValue, setInputValue] = useState('')

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      const trimmed = inputValue.trim().toLowerCase()
      if (trimmed && !tags.includes(trimmed)) {
        onAdd(trimmed)
      }
      setInputValue('')
    }
  }

  const accentColor = variant === 'include' ? 'focus:border-blue-500' : 'focus:border-red-500'
  const labelColor = variant === 'include' ? 'text-blue-400' : 'text-red-400'

  return (
    <div className="flex flex-col gap-2">
      <label className={`text-xs font-semibold uppercase tracking-wider ${labelColor}`}>
        {label}
      </label>

      <input
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className={`
          w-full px-3 py-1.5
          bg-vault-input border border-vault-border rounded
          text-vault-text text-sm placeholder-vault-text-muted
          outline-none transition-colors duration-150
          ${accentColor}
        `}
        aria-label={label}
      />

      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <TagBadge
              key={tag}
              tag={tag}
              variant={variant}
              onRemove={() => onRemove(tag)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function TagInput({
  includeTags,
  excludeTags,
  onAddInclude,
  onRemoveInclude,
  onAddExclude,
  onRemoveExclude,
}: TagInputProps) {
  return (
    <div className="flex flex-col gap-4">
      <TagField
        label="Include Tags"
        tags={includeTags}
        variant="include"
        placeholder="e.g. character:reimu — press Enter"
        onAdd={onAddInclude}
        onRemove={onRemoveInclude}
      />
      <TagField
        label="Exclude Tags"
        tags={excludeTags}
        variant="exclude"
        placeholder="e.g. artist:foo — press Enter"
        onAdd={onAddExclude}
        onRemove={onRemoveExclude}
      />
    </div>
  )
}
