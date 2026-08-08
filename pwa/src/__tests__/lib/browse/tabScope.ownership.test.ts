import { describe, expect, it } from 'vitest'
import { claimBrowseTabScope } from '@/lib/browse/tabScope'

type ChannelMessage = Record<string, unknown>
type MessageListener = (event: { data: ChannelMessage }) => void
type Channel = {
  postMessage: (message: ChannelMessage) => void
  addEventListener: (type: 'message', listener: MessageListener) => void
  removeEventListener: (type: 'message', listener: MessageListener) => void
  close: () => void
}

class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() { return this.values.size }
  clear() { this.values.clear() }
  getItem(key: string) { return this.values.get(key) ?? null }
  key(index: number) { return [...this.values.keys()][index] ?? null }
  removeItem(key: string) { this.values.delete(key) }
  setItem(key: string, value: string) { this.values.set(key, value) }
  clone(): MemoryStorage {
    const copy = new MemoryStorage()
    for (let index = 0; index < this.length; index += 1) {
      const key = this.key(index)
      if (key) copy.setItem(key, this.getItem(key)!)
    }
    return copy
  }
}

function createChannelFactory(
  schedule: (callback: () => void) => void = (callback) => queueMicrotask(callback),
) {
  const listeners = new Set<MessageListener>()
  return (_name: string): Channel => {
    const owned = new Set<MessageListener>()
    return {
      postMessage(message) {
        schedule(() => {
          for (const listener of listeners) {
            if (!owned.has(listener)) listener({ data: message })
          }
        })
      },
      addEventListener(_type, listener) {
        owned.add(listener)
        listeners.add(listener)
      },
      removeEventListener(_type, listener) {
        owned.delete(listener)
        listeners.delete(listener)
      },
      close() {
        for (const listener of owned) listeners.delete(listener)
        owned.clear()
      },
    }
  }
}

async function waitForMicrotaskProbe(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('browse tab-scope ownership', () => {
  it('rotates a cloned session ID on a live ownership collision', async () => {
    const channelFactory = createChannelFactory()
    const originalStorage = new MemoryStorage()
    const original = await claimBrowseTabScope({
      storage: originalStorage,
      channelFactory,
      waitForProbe: waitForMicrotaskProbe,
    })
    const duplicatedStorage = originalStorage.clone()

    const duplicated = await claimBrowseTabScope({
      storage: duplicatedStorage,
      channelFactory,
      waitForProbe: waitForMicrotaskProbe,
    })

    expect(duplicated.tabId).not.toBe(original.tabId)
    expect(duplicatedStorage.getItem('browse_session_tab_id_v1')).toBe(duplicated.tabId)
    duplicated.release()
    original.release()
  })

  it('lets a reload reclaim the stored ID after the old document releases ownership', async () => {
    const channelFactory = createChannelFactory()
    const storage = new MemoryStorage()
    const first = await claimBrowseTabScope({
      storage,
      channelFactory,
      waitForProbe: waitForMicrotaskProbe,
    })
    const storedId = first.tabId
    first.release()

    const reloaded = await claimBrowseTabScope({
      storage,
      channelFactory,
      waitForProbe: waitForMicrotaskProbe,
    })

    expect(reloaded.tabId).toBe(storedId)
    reloaded.release()
  })

  it('resolves simultaneous cloned contenders to distinct IDs', async () => {
    const channelFactory = createChannelFactory()
    const seed = new MemoryStorage()
    seed.setItem('browse_session_tab_id_v1', 'cloned-tab')

    const [left, right] = await Promise.all([
      claimBrowseTabScope({
        storage: seed.clone(),
        channelFactory,
        now: () => 100,
        waitForProbe: waitForMicrotaskProbe,
      }),
      claimBrowseTabScope({
        storage: seed.clone(),
        channelFactory,
        now: () => 100,
        waitForProbe: waitForMicrotaskProbe,
      }),
    ])

    expect(left.tabId).not.toBe(right.tabId)
    left.release()
    right.release()
  })

  it('waits through task-delivered messages before accepting a duplicated tab ID', async () => {
    const channelFactory = createChannelFactory((callback) => setTimeout(callback, 0))
    const waitForTaskProbe = () => new Promise<void>((resolve) => setTimeout(resolve, 10))
    const originalStorage = new MemoryStorage()
    const original = await claimBrowseTabScope({
      storage: originalStorage,
      channelFactory,
      waitForProbe: waitForTaskProbe,
    })
    const duplicatedStorage = originalStorage.clone()

    const duplicated = await claimBrowseTabScope({
      storage: duplicatedStorage,
      channelFactory,
      waitForProbe: waitForTaskProbe,
    })

    expect(duplicated.tabId).not.toBe(original.tabId)
    duplicated.release()
    original.release()
  })

  it('rotates and notifies the owner when occupied arrives after the initial probe window', async () => {
    const channelFactory = createChannelFactory((callback) => setTimeout(callback, 45))
    const waitForInitialProbe = () => new Promise<void>((resolve) => setTimeout(resolve, 32))
    const originalStorage = new MemoryStorage()
    const original = await claimBrowseTabScope({
      storage: originalStorage,
      channelFactory,
      waitForProbe: waitForInitialProbe,
    })
    await new Promise((resolve) => setTimeout(resolve, 20))
    const duplicatedStorage = originalStorage.clone()
    const duplicated = await claimBrowseTabScope({
      storage: duplicatedStorage,
      channelFactory,
      waitForProbe: waitForInitialProbe,
    })
    const reactiveClaim = duplicated as typeof duplicated & {
      onTabIdChange: (listener: (tabId: string) => void) => () => void
    }
    const changes: string[] = []
    const unsubscribe =
      typeof reactiveClaim.onTabIdChange === 'function'
        ? reactiveClaim.onTabIdChange((tabId) => {
            if (tabId !== null) changes.push(tabId)
          })
        : undefined

    await new Promise((resolve) => setTimeout(resolve, 120))

    expect(typeof reactiveClaim.onTabIdChange).toBe('function')
    expect(reactiveClaim.tabId).not.toBe(original.tabId)
    expect(duplicatedStorage.getItem('browse_session_tab_id_v1')).toBe(reactiveClaim.tabId)
    expect(changes.at(-1)).toBe(reactiveClaim.tabId)
    unsubscribe?.()
    duplicated.release()
    original.release()
  })

  it('falls back safely to one stable in-memory ID when storage and channels are unavailable', async () => {
    const storage = {
      get length(): number { throw new DOMException('blocked', 'SecurityError') },
      clear() { throw new DOMException('blocked', 'SecurityError') },
      getItem() { throw new DOMException('blocked', 'SecurityError') },
      key() { throw new DOMException('blocked', 'SecurityError') },
      removeItem() { throw new DOMException('blocked', 'SecurityError') },
      setItem() { throw new DOMException('blocked', 'SecurityError') },
    } satisfies Storage
    const channelFactory = () => {
      throw new DOMException('blocked', 'SecurityError')
    }

    const first = await claimBrowseTabScope({ storage, channelFactory })
    first.release()
    const second = await claimBrowseTabScope({ storage, channelFactory })

    expect(second.tabId).toBe(first.tabId)
    second.release()
  })
})
