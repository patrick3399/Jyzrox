import { commitBrowseUrl, type BrowseHistoryMode } from '@/lib/browse/browseHistory'

/** Per-tab bookkeeping that lets the Explorer decide between "history back"
 *  (return to the exact list the user pushed from) and "push the parent".
 *
 *  Everything lives in sessionStorage keyed by URL — never in `history.state`,
 *  which the App Router owns (FE-T17). */

const STACK_KEY = 'explorer:pushStack'
const SCROLL_KEY = 'explorer:scroll'
const STACK_CAP = 60
const SCROLL_CAP = 30

interface PushEntry {
  /** The Explorer URL the user was on when they pushed. */
  from: string
  /** The URL that push produced (kept current when it is refined in place). */
  to: string
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Quota or private mode: history still works, only the shortcut is lost.
  }
}

function loadStack(): PushEntry[] {
  const value = readJson<unknown>(STACK_KEY, [])
  return Array.isArray(value) ? (value as PushEntry[]).filter((entry) => typeof entry?.from === 'string' && typeof entry?.to === 'string') : []
}

function recordPush(from: string, to: string): void {
  const stack = loadStack()
  // Drop entries that are no longer behind the current history position.
  while (stack.length > 0 && stack[stack.length - 1].to !== from) stack.pop()
  stack.push({ from, to })
  writeJson(STACK_KEY, stack.slice(-STACK_CAP))
}

function recordReplace(from: string, to: string): void {
  const stack = loadStack()
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    if (stack[index].to === from) {
      stack[index] = { ...stack[index], to }
      writeJson(STACK_KEY, stack)
      return
    }
  }
}

/** True when the entry before `current` in this tab is the Explorer URL we pushed from. */
export function canStepBackInHistory(current: string): boolean {
  return loadStack().some((entry) => entry.to === current)
}

// --- scroll positions -------------------------------------------------------

export function saveScroll(url: string, top: number): void {
  const entries = readJson<Array<[string, number]>>(SCROLL_KEY, []).filter(([key]) => key !== url)
  entries.push([url, Math.round(top)])
  writeJson(SCROLL_KEY, entries.slice(-SCROLL_CAP))
}

export function loadScroll(url: string): number | null {
  const entry = readJson<Array<[string, number]>>(SCROLL_KEY, []).find(([key]) => key === url)
  return entry && Number.isFinite(entry[1]) && entry[1] > 0 ? entry[1] : null
}

function forgetScroll(url: string): void {
  const entries = readJson<Array<[string, number]>>(SCROLL_KEY, [])
  const next = entries.filter(([key]) => key !== url)
  if (next.length !== entries.length) writeJson(SCROLL_KEY, next)
}

const scrollSavers = new Set<() => void>()

/** Mounted scroll containers register a capture callback so a push can save
 *  the position of the list it is leaving. Returns the unregister function. */
export function registerScrollSaver(saver: () => void): () => void {
  scrollSavers.add(saver)
  return () => { scrollSavers.delete(saver) }
}

export function saveExplorerScroll(): void {
  scrollSavers.forEach((saver) => saver())
}

// --- coarse-pointer selection entry ----------------------------------------

let selectionEntryLive = false

/** Selection mode on coarse pointers pushes a duplicate entry so the system
 *  back gesture exits selection first. While that entry is on top of the
 *  stack, our own push replaces it instead of stacking on it, and "back"
 *  skips over it — otherwise the user needs two backs to leave a list. */
export function markSelectionEntry(): void {
  selectionEntryLive = true
  window.addEventListener('popstate', () => { selectionEntryLive = false }, { once: true })
}

export function hasSelectionEntry(): boolean {
  return selectionEntryLive
}

// --- writes -----------------------------------------------------------------

export function commitExplorerUrl(from: string, to: string, mode: BrowseHistoryMode): void {
  if (from === to) return
  if (mode === 'replace') {
    recordReplace(from, to)
    commitBrowseUrl(to, 'replace')
    return
  }
  saveExplorerScroll()
  forgetScroll(to)
  recordPush(from, to)
  if (selectionEntryLive) {
    selectionEntryLive = false
    commitBrowseUrl(to, 'replace')
  } else {
    commitBrowseUrl(to, 'push')
  }
}

export function stepBackInHistory(): void {
  saveExplorerScroll()
  if (selectionEntryLive) window.history.go(-2)
  else window.history.back()
}
