import type { ReactNode } from 'react'
import { resolveCategoryColors } from '@/lib/categoryPalette'
import type { GalleryCategoryDef } from '@/lib/types'

interface ThumbPlaceholderProps {
  category: string | null | undefined
  categories?: GalleryCategoryDef[]
  className?: string
  children?: ReactNode
}

/**
 * Stand-in for a page or cover whose thumbnail does not exist yet (a gallery
 * that is still downloading, a pending link page). Same category gradient the
 * library grid uses for a gallery without a cover.
 */
export function ThumbPlaceholder({
  category,
  categories,
  className = '',
  children,
}: ThumbPlaceholderProps) {
  const colors = resolveCategoryColors(category, categories)
  return (
    <div
      className={`bg-gradient-to-b ${colors.bg} ${colors.text} flex items-center justify-center text-xs font-semibold ${className}`}
    >
      {children}
    </div>
  )
}
