import type { LucideIcon } from 'lucide-react'
import {
  Globe,
  BookOpen,
  Paintbrush,
  Ban,
  HardDrive,
  User,
  KeyRound,
  Monitor,
  Shield,
  ToggleRight,
  Gauge,
  Wrench,
  ScrollText,
  Bot,
  CalendarClock,
} from 'lucide-react'
import { hasRole } from '@/lib/pageRegistry'
import type { UserRole } from '@/lib/types'

export type SettingsGroup = 'personal' | 'appearance' | 'account' | 'admin'

export interface SettingsCategoryDef {
  slug: string
  labelKey: string
  descKey: string
  icon: LucideIcon
  minRole?: UserRole
  group: SettingsGroup
}

export const SETTINGS_CATEGORIES: SettingsCategoryDef[] = [
  // ── Personal ──
  {
    slug: 'general',
    labelKey: 'settingsCategory.general',
    descKey: 'settingsCategory.generalDesc',
    icon: Globe,
    group: 'personal',
  },
  {
    slug: 'reader',
    labelKey: 'settingsCategory.reader',
    descKey: 'settingsCategory.readerDesc',
    icon: BookOpen,
    group: 'personal',
  },
  {
    slug: 'blocked-tags',
    labelKey: 'settingsCategory.blockedTags',
    descKey: 'settingsCategory.blockedTagsDesc',
    icon: Ban,
    group: 'personal',
  },
  {
    slug: 'cache',
    labelKey: 'settingsCategory.cache',
    descKey: 'settingsCategory.cacheDesc',
    icon: HardDrive,
    group: 'personal',
  },

  // ── Appearance ──
  {
    slug: 'appearance',
    labelKey: 'settingsCategory.appearance',
    descKey: 'settingsCategory.appearanceDesc',
    icon: Paintbrush,
    group: 'appearance',
  },

  // ── Account ──
  {
    slug: 'account',
    labelKey: 'settingsCategory.account',
    descKey: 'settingsCategory.accountDesc',
    icon: User,
    group: 'account',
  },
  {
    slug: 'api-tokens',
    labelKey: 'settingsCategory.apiTokens',
    descKey: 'settingsCategory.apiTokensDesc',
    icon: KeyRound,
    group: 'account',
  },

  // ── Admin ──
  {
    slug: 'system',
    labelKey: 'settingsCategory.system',
    descKey: 'settingsCategory.systemDesc',
    icon: Monitor,
    minRole: 'admin',
    group: 'admin',
  },
  {
    slug: 'security',
    labelKey: 'settingsCategory.security',
    descKey: 'settingsCategory.securityDesc',
    icon: Shield,
    minRole: 'admin',
    group: 'admin',
  },
  {
    slug: 'features',
    labelKey: 'settingsCategory.features',
    descKey: 'settingsCategory.featuresDesc',
    icon: ToggleRight,
    minRole: 'admin',
    group: 'admin',
  },
  {
    slug: 'rate-limits',
    labelKey: 'settingsCategory.rateLimits',
    descKey: 'settingsCategory.rateLimitsDesc',
    icon: Gauge,
    minRole: 'admin',
    group: 'admin',
  },
  {
    slug: 'workers',
    labelKey: 'settingsCategory.workers',
    descKey: 'settingsCategory.workersDesc',
    icon: Wrench,
    minRole: 'admin',
    group: 'admin',
  },
  {
    slug: 'logging',
    labelKey: 'settingsCategory.logging',
    descKey: 'settingsCategory.loggingDesc',
    icon: ScrollText,
    minRole: 'admin',
    group: 'admin',
  },
  {
    slug: 'ai-tagging',
    labelKey: 'settingsCategory.aiTagging',
    descKey: 'settingsCategory.aiTaggingDesc',
    icon: Bot,
    minRole: 'admin',
    group: 'admin',
  },
  {
    slug: 'scheduled',
    labelKey: 'settingsCategory.scheduled',
    descKey: 'settingsCategory.scheduledDesc',
    icon: CalendarClock,
    minRole: 'admin',
    group: 'admin',
  },
]

const GROUP_ORDER: SettingsGroup[] = ['personal', 'appearance', 'account', 'admin']

const GROUP_LABEL_KEYS: Record<SettingsGroup, string> = {
  personal: 'settingsGroup.personal',
  appearance: 'settingsGroup.appearance',
  account: 'settingsGroup.account',
  admin: 'settingsGroup.admin',
}

export function getVisibleCategories(role?: string): SettingsCategoryDef[] {
  return SETTINGS_CATEGORIES.filter((c) => hasRole(role, c.minRole ?? 'viewer'))
}

export function getSettingsGroups(role?: string) {
  const visible = getVisibleCategories(role)
  return GROUP_ORDER.map((group) => ({
    group,
    labelKey: GROUP_LABEL_KEYS[group],
    categories: visible.filter((c) => c.group === group),
  })).filter((g) => g.categories.length > 0)
}
