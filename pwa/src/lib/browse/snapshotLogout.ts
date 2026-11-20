// Superseded by the scoped partitions below. Safe to delete outright once the
// compatibility migrations that read them are retired.
const RETIRED_BROWSE_KEYS = [
  'eh_browse_snapshot',
  'library_scrollY',
  'pixiv_ranking_scrollY',
  'pixiv_feed_scrollY',
  'pixiv_bookmarks_scrollY',
  'pixiv_search_scrollY',
] as const

// Current-generation keys owned by the live navigation and tab-scope modules.
// They are cleared on logout — not because they are obsolete, but because the
// next session in this tab must not inherit the previous user's browsing
// position or tab identity. Do not fold these into the retired list.
const ACTIVE_PER_USER_BROWSE_KEYS = [
  'nav_memory_v1',
  'nav_restore_flag_v1',
  'browse_session_tab_id_v1',
] as const

const KEYS_CLEARED_ON_LOGOUT = new Set<string>([
  ...RETIRED_BROWSE_KEYS,
  ...ACTIVE_PER_USER_BROWSE_KEYS,
])

export function clearBrowseSessionStorage(storage: Storage): void {
  const remove: string[] = []
  let length: number
  try {
    length = storage.length
  } catch {
    return
  }
  for (let index = 0; index < length; index += 1) {
    let key: string | null
    try {
      key = storage.key(index)
    } catch {
      continue
    }
    if (key && (KEYS_CLEARED_ON_LOGOUT.has(key) || key.startsWith('browse_session_v1:'))) {
      remove.push(key)
    }
  }
  for (const key of remove) {
    try {
      storage.removeItem(key)
    } catch {
      // Logout cleanup is best effort; one inaccessible key must not prevent
      // the remaining scoped and legacy partitions from being invalidated.
    }
  }
}
