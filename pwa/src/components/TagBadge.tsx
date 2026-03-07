interface TagBadgeProps {
  tag: string
  onClick?: () => void
  onRemove?: () => void
  variant?: 'default' | 'include' | 'exclude'
}

function getNamespaceStyles(namespace: string): string {
  switch (namespace) {
    case 'character':
      return 'text-purple-300 bg-purple-900/30 border-purple-700'
    case 'artist':
      return 'text-orange-300 bg-orange-900/30 border-orange-700'
    case 'copyright':
      return 'text-green-300 bg-green-900/30 border-green-700'
    case 'general':
    default:
      return 'text-vault-text-secondary bg-vault-input border-vault-border'
  }
}

function getVariantStyles(variant: 'default' | 'include' | 'exclude'): string {
  switch (variant) {
    case 'include':
      return 'ring-1 ring-blue-500'
    case 'exclude':
      return 'ring-1 ring-red-500'
    default:
      return ''
  }
}

export function TagBadge({ tag, onClick, onRemove, variant = 'default' }: TagBadgeProps) {
  const colonIndex = tag.indexOf(':')
  const namespace = colonIndex !== -1 ? tag.slice(0, colonIndex) : 'general'
  const name = colonIndex !== -1 ? tag.slice(colonIndex + 1) : tag

  const namespaceStyles = getNamespaceStyles(namespace)
  const variantStyles = getVariantStyles(variant)
  const isExclude = variant === 'exclude'

  const baseClasses = `
    inline-flex items-center gap-1
    px-2 py-0.5
    rounded border text-xs font-mono
    transition-colors duration-150
    ${namespaceStyles}
    ${variantStyles}
  `

  const clickableClasses = onClick ? 'cursor-pointer hover:brightness-125' : ''

  return (
    <span
      className={`${baseClasses} ${clickableClasses}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      {colonIndex !== -1 && (
        <span className="opacity-60">{namespace}:</span>
      )}
      <span className={isExclude ? 'line-through' : ''}>{name}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          className="ml-0.5 opacity-60 hover:opacity-100 leading-none"
          aria-label={`Remove tag ${tag}`}
        >
          ×
        </button>
      )}
    </span>
  )
}
