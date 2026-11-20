import type { LucideIcon } from 'lucide-react'
import type { UserRole } from '@/lib/types'

export interface PageDef {
  href: string
  labelKey: string
  descKey?: string
  icon: LucideIcon
  /** Appears in the BottomTabBar candidate pool */
  nav: boolean
  /** Appears in the Dashboard Quick Links grid */
  dashboard: boolean
  /** Appears in sidebar navigation */
  sidebar: boolean
  /** Minimum role required to see this page */
  minRole?: UserRole
  /** Feature-toggle key from GET /api/settings/features; page is hidden unless that flag is true */
  featureFlag?: string
}

export function hasRole(userRole: string | undefined, minRole: UserRole): boolean {
  const ROLE_LEVEL: Record<string, number> = { admin: 3, member: 2, viewer: 1 }
  return (ROLE_LEVEL[userRole || 'viewer'] ?? 0) >= ROLE_LEVEL[minRole]
}

/**
 * A page passes when it declares no feature flag, or when the flag is
 * explicitly enabled. While features are still loading (undefined) a flagged
 * page stays hidden so a default-off feature never flashes a link that 404s.
 */
export function passesFeatureFlag(
  page: PageDef,
  features: Record<string, boolean | number> | undefined,
): boolean {
  if (!page.featureFlag) return true
  return features?.[page.featureFlag] === true
}
