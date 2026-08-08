'use client'

import { useEffect, useState } from 'react'
import { claimBrowseTabScope, commitBrowseTabId } from '@/lib/browse/tabScope'

type UseBrowseTabScopeOptions = {
  storage: Storage
  enabled: boolean
  requestedTabId?: string
}

export function useBrowseTabScope({
  storage,
  enabled,
  requestedTabId,
}: UseBrowseTabScopeOptions): { tabId: string; ready: boolean } {
  const [claimedTabId, setClaimedTabId] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled || requestedTabId) {
      setClaimedTabId(null)
      return
    }
    let active = true
    let attempt = 0
    let claimPending = false
    let release: (() => void) | undefined
    let unsubscribe: (() => void) | undefined
    let controller: AbortController | undefined
    let activeTabId: string | null = null
    const acquire = () => {
      if (claimPending || release) return
      const currentAttempt = ++attempt
      claimPending = true
      controller = new AbortController()
      setClaimedTabId(null)
      void claimBrowseTabScope({ storage, signal: controller.signal })
        .then((claim) => {
          if (!active || currentAttempt !== attempt) {
            claim.release()
            if (activeTabId) commitBrowseTabId(storage, activeTabId)
            return
          }
          claimPending = false
          release = claim.release
          activeTabId = claim.tabId
          unsubscribe = claim.onTabIdChange?.((tabId) => {
            if (!active || currentAttempt !== attempt) return
            activeTabId = tabId
            setClaimedTabId(tabId)
          })
          setClaimedTabId(claim.tabId)
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === 'AbortError') return
          if (!active || currentAttempt !== attempt) return
          claimPending = false
          setClaimedTabId(null)
        })
    }
    const releaseCurrent = (publish: boolean) => {
      attempt += 1
      claimPending = false
      controller?.abort()
      controller = undefined
      unsubscribe?.()
      unsubscribe = undefined
      release?.()
      release = undefined
      activeTabId = null
      if (publish) setClaimedTabId(null)
    }
    const onPageHide = () => releaseCurrent(true)
    const onPageShow = () => acquire()
    window.addEventListener('pagehide', onPageHide)
    window.addEventListener('pageshow', onPageShow)
    acquire()
    return () => {
      active = false
      window.removeEventListener('pagehide', onPageHide)
      window.removeEventListener('pageshow', onPageShow)
      releaseCurrent(false)
    }
  }, [enabled, requestedTabId, storage])

  if (!enabled) return { tabId: 'pending', ready: false }
  if (requestedTabId) return { tabId: requestedTabId, ready: true }
  return claimedTabId
    ? { tabId: claimedTabId, ready: true }
    : { tabId: 'pending', ready: false }
}
