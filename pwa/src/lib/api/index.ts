// ── Aggregated API client ────────────────────────────────────────────
//
// This module is the single public entry point for `@/lib/api`. It re-exports
// every per-feature client module and assembles the `api` object with the
// exact same shape as the original monolithic `lib/api.ts` (architecture
// risk #9). Do not import the per-feature modules directly from outside
// `lib/api/` — always go through `@/lib/api` so the aggregate stays the
// single source of truth.

import { auth } from './auth'
import { eh } from './eh'
import { library } from './library'
import { explorer } from './explorer'
import { download } from './download'
import { settings } from './settings'
import { system } from './system'
import { tags } from './tags'
import { tokens } from './tokens'
import { exportApi } from './export'
import { import_ } from './import'
import { history, savedSearches } from './history'
import { plugins, processing, training } from './plugins'
import { galleryManagement } from './galleryManagement'
import { pixiv } from './pixiv'
import { artists } from './artists'
import { collections } from './collections'
import { datasets } from './datasets'
import { scheduledTasks, backups } from './scheduledTasks'
import { subscriptions, subscriptionGroups } from './subscriptions'
import { dedup } from './dedup'
import { users } from './users'
import { logs, galleryDl } from './logs'
import { adminSites, adminQueue } from './admin'
import { search } from './search'
import { saucenao } from './saucenao'
import { novels } from './novels'

export const api = {
  auth,
  eh,
  library,
  explorer,
  download,
  settings,
  system,
  tags,
  tokens,
  export: exportApi,
  import_,
  history,
  savedSearches,
  plugins,
  processing,
  training,
  galleryManagement,
  pixiv,
  artists,
  collections,
  datasets,
  scheduledTasks,
  backups,
  subscriptions,
  subscriptionGroups,
  dedup,
  users,
  logs,
  adminSites,
  galleryDl,
  adminQueue,
  search,
  saucenao,
  novels,
}

// ── Re-exported types (preserve `@/lib/api` as the single import surface) ──

export type { ReconcileStatus } from './system'
export type { ExplorerQuery, ExplorerGalleryItem, ExplorerRoots, ExplorerPhysicalEntry } from './explorer'
export type { SearchGalleryItem, SearchGalleriesResponse } from './search'
export type { SauceNaoResult } from './saucenao'
export type {
  NovelWork,
  NovelChapter,
  NovelCategoryCounts,
  NovelAct,
  NovelFile,
  NovelSearchHit,
  NovelCommit,
  NovelRepoStatus,
  NovelWriteResult,
  NovelGraphNode,
  NovelGraphEdge,
  NovelGraph,
  NovelNoteSummary,
  NovelAppearance,
  NovelFormatIssue,
  NovelFileIssues,
} from './novels'
