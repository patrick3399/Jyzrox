const STORAGE_KEY = 'nav_memory_v1'

type NavMemoryMap = Record<string, string>

function readMap(): NavMemoryMap {
  if (typeof window === 'undefined') return {}
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as NavMemoryMap
    }
  } catch {
    // malformed — treat as empty
  }
  return {}
}

function writeMap(map: NavMemoryMap): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    // quota / disabled storage — best effort
  }
}

/** Longest tab root that owns `pathname` (exact match or `root` + '/' segment), else null. */
export function resolveTabRoot(roots: string[], pathname: string): string | null {
  let best: string | null = null
  for (const root of roots) {
    if (root === '/') continue
    if (pathname === root || pathname.startsWith(root + '/')) {
      if (best === null || root.length > best.length) best = root
    }
  }
  return best
}

/** Record the full URL (path + optional query) under its owning tab root.
 *  A root-level visit is also banked separately (`list:` entry) so back
 *  buttons can climb to the section list even when the tab entry points at a
 *  deep sub-page. */
export function rememberLocation(roots: string[], pathname: string, search: string): void {
  const root = resolveTabRoot(roots, pathname)
  if (!root) return
  const map = readMap()
  const url = search ? `${pathname}?${search}` : pathname
  map[root] = url
  if (pathname === root) map[`list:${root}`] = url
  writeMap(map)
}

/** Remembered full URL for a tab root, or the bare root if none. */
export function getTabHref(root: string): string {
  return readMap()[root] ?? root
}

/** Last URL seen at the section root itself (list level), or the bare root. */
export function getListHref(root: string): string {
  return readMap()[`list:${root}`] ?? root
}

export function clearTabMemory(root: string): void {
  const map = readMap()
  delete map[root]
  delete map[`list:${root}`]
  writeMap(map)
}

// ── Tab-restore marking ─────────────────────────────────────────────────
// When a nav tab jumps to a remembered DEEP url (sub-page), the browser
// history's previous entry is whatever unrelated section the user detoured
// through — so "back" on the restored page must climb to the section list
// instead of history-backing out of the section.

const RESTORE_FLAG_KEY = 'nav_restore_flag_v1'

/** Flag the destination of a tab restore that points at a deep sub-page. */
export function markTabRestore(url: string): void {
  try {
    sessionStorage.setItem(RESTORE_FLAG_KEY, url)
  } catch {
    /* best effort */
  }
}

/** True when `currentUrl` is the destination of the last tab restore. One-shot. */
export function consumeTabRestore(currentUrl: string): boolean {
  try {
    if (sessionStorage.getItem(RESTORE_FLAG_KEY) !== currentUrl) return false
    sessionStorage.removeItem(RESTORE_FLAG_KEY)
    return true
  } catch {
    return false
  }
}
