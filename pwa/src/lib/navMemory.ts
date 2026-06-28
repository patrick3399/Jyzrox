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

/** Record the full URL (path + optional query) under its owning tab root. */
export function rememberLocation(roots: string[], pathname: string, search: string): void {
  const root = resolveTabRoot(roots, pathname)
  if (!root) return
  const map = readMap()
  map[root] = search ? `${pathname}?${search}` : pathname
  writeMap(map)
}

/** Remembered full URL for a tab root, or the bare root if none. */
export function getTabHref(root: string): string {
  return readMap()[root] ?? root
}

export function clearTabMemory(root: string): void {
  const map = readMap()
  delete map[root]
  writeMap(map)
}
