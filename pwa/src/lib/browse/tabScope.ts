const TAB_ID_KEY = 'browse_session_tab_id_v1'
const TAB_SCOPE_CHANNEL = 'jyzrox:browse-tab-scope:v1'
const fallbackTabIds = new WeakMap<object, string>()

function generateTabId(now: () => number = Date.now): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `tab-${now()}-${Math.random().toString(36).slice(2)}`
}

function getFallbackTabId(storage: Storage): string {
  const existing = fallbackTabIds.get(storage)
  if (existing) return existing
  const generated = generateTabId()
  fallbackTabIds.set(storage, generated)
  return generated
}

export function getBrowseTabId(storage: Storage): string {
  let existing: string | null
  try {
    existing = storage.getItem(TAB_ID_KEY)
  } catch {
    return getFallbackTabId(storage)
  }
  if (existing) return existing
  const generated = getFallbackTabId(storage)
  try {
    storage.setItem(TAB_ID_KEY, generated)
  } catch {
    // Storage is best effort. The WeakMap keeps this tab scope stable in memory.
  }
  return generated
}

type BrowseTabChannelMessage = Record<string, unknown>
type BrowseTabChannelListener = (event: { data: BrowseTabChannelMessage }) => void

export type BrowseTabChannel = {
  postMessage: (message: BrowseTabChannelMessage) => void
  addEventListener: (type: 'message', listener: BrowseTabChannelListener) => void
  removeEventListener: (type: 'message', listener: BrowseTabChannelListener) => void
  close: () => void
}

export type BrowseTabScopeClaim = {
  readonly tabId: string
  onTabIdChange: (listener: (tabId: string | null) => void) => () => void
  release: () => void
}

type ClaimBrowseTabScopeOptions = {
  storage: Storage
  channelFactory?: (name: string) => BrowseTabChannel
  now?: () => number
  waitForProbe?: () => Promise<void>
  signal?: AbortSignal
}

function readStoredTabId(storage: Storage): string | null {
  try {
    return storage.getItem(TAB_ID_KEY)
  } catch {
    return null
  }
}

function persistTabId(storage: Storage, tabId: string): void {
  try {
    storage.setItem(TAB_ID_KEY, tabId)
  } catch {
    // The in-memory fallback remains stable for this Storage object.
  }
}

export function commitBrowseTabId(storage: Storage, tabId: string): void {
  fallbackTabIds.set(storage, tabId)
  persistTabId(storage, tabId)
}

function abortError(): DOMException {
  return new DOMException('Browse tab claim aborted', 'AbortError')
}

function waitForBroadcastProbe(): Promise<void> {
  // BroadcastChannel dispatches `message` as a task, not a microtask. Keep the
  // initial scope closed for a short bounded window so both the contender and
  // an incumbent's occupied reply can be delivered before snapshots open.
  return new Promise((resolve) => setTimeout(resolve, 32))
}

/**
 * Claims a live document's browse-tab ID. sessionStorage is copied when a
 * browser tab is duplicated, so storage alone is not a sufficient ownership
 * boundary. Live contenders coordinate before a snapshot scope is opened.
 */
export async function claimBrowseTabScope({
  storage,
  channelFactory = (name) => new BroadcastChannel(name) as BrowseTabChannel,
  now = Date.now,
  waitForProbe = waitForBroadcastProbe,
  signal,
}: ClaimBrowseTabScopeOptions): Promise<BrowseTabScopeClaim> {
  if (signal?.aborted) throw abortError()
  const stored = readStoredTabId(storage)
  let candidate = stored ?? getFallbackTabId(storage)

  for (;;) {
    let channel: BrowseTabChannel
    try {
      channel = channelFactory(TAB_SCOPE_CHANNEL)
    } catch {
      if (signal?.aborted) throw abortError()
      commitBrowseTabId(storage, candidate)
      return {
        get tabId() {
          return candidate
        },
        onTabIdChange: () => () => undefined,
        release: () => undefined,
      }
    }

    const contenderId = generateTabId(now)
    let claimed = false
    let collision = false
    let released = false
    let rotating = false
    let currentTabId = candidate
    const changeListeners = new Set<(tabId: string | null) => void>()
    const notify = (tabId: string | null) => {
      for (const changeListener of changeListeners) changeListener(tabId)
    }
    const rotateAfterLateCollision = async () => {
      if (released || rotating || signal?.aborted) return
      rotating = true
      claimed = false
      notify(null)
      try {
        for (;;) {
          if (released || signal?.aborted) return
          candidate = generateTabId(now)
          collision = false
          channel.postMessage({ type: 'contend', tabId: candidate, contenderId })
          await waitForProbe()
          if (released || signal?.aborted) return
          if (collision) continue
          currentTabId = candidate
          commitBrowseTabId(storage, currentTabId)
          claimed = true
          notify(currentTabId)
          return
        }
      } finally {
        rotating = false
      }
    }
    const listener: BrowseTabChannelListener = ({ data }) => {
      if (data.tabId !== candidate || data.contenderId === contenderId) return
      if (data.type === 'occupied' && data.requesterId === contenderId) {
        if (claimed) {
          void rotateAfterLateCollision()
          return
        }
        collision = true
        return
      }
      if (data.type !== 'contend') return
      const requesterId = typeof data.contenderId === 'string' ? data.contenderId : ''
      if (claimed) {
        channel.postMessage({
          type: 'occupied',
          tabId: candidate,
          contenderId,
          requesterId,
        })
        return
      }
      // Simultaneous contenders deterministically choose one winner. The
      // losing document rotates its copied ID before opening a snapshot store.
      if (requesterId && contenderId.localeCompare(requesterId) > 0) collision = true
    }
    channel.addEventListener('message', listener)
    channel.postMessage({ type: 'contend', tabId: candidate, contenderId })
    await waitForProbe()

    if (signal?.aborted) {
      released = true
      channel.removeEventListener('message', listener)
      channel.close()
      throw abortError()
    }

    if (collision) {
      channel.removeEventListener('message', listener)
      channel.close()
      candidate = generateTabId(now)
      continue
    }

    claimed = true
    currentTabId = candidate
    commitBrowseTabId(storage, currentTabId)
    return {
      get tabId() {
        return currentTabId
      },
      onTabIdChange: (changeListener) => {
        changeListeners.add(changeListener)
        return () => changeListeners.delete(changeListener)
      },
      release: () => {
        if (released) return
        released = true
        changeListeners.clear()
        channel.removeEventListener('message', listener)
        channel.close()
      },
    }
  }
}
