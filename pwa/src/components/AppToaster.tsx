'use client'

import { useEffect } from 'react'
import { Toaster, type ToasterProps } from 'sonner'

const TOASTER_SELECTOR = '[data-sonner-toaster]'

/** Above the mobile BottomTabBar; the value lives in globals.css because the bar is lg:hidden. */
const ABOVE_TAB_BAR = 'var(--toast-offset-bottom)'

/**
 * Sonner pauses every toast's auto-dismiss timer while its Toaster is
 * "interacting", which it sets on pointerdown and clears only on pointerup.
 * It ignores pointercancel. When an OS gesture (home-indicator swipe, app
 * switcher, gesture navigation) starts on a toast, the browser cancels the
 * pointer or hides the page without a pointerup, and the toasts never close.
 *
 * Track presses that start inside the toaster and, when one ends without a
 * pointerup, deliver a synthetic pointerup so sonner resets its state.
 */
function useReleaseCancelledToastPresses() {
  useEffect(() => {
    const pressed = new Map<number, Element>()

    const release = (pointerId: number) => {
      const target = pressed.get(pointerId)
      pressed.delete(pointerId)
      if (!target) return
      const node = target.isConnected ? target : document.querySelector(TOASTER_SELECTOR)
      if (!node) return
      const init = { bubbles: true, cancelable: true, pointerId, isPrimary: true }
      node.dispatchEvent(
        typeof PointerEvent === 'function'
          ? new PointerEvent('pointerup', init)
          : new MouseEvent('pointerup', init),
      )
    }
    const releaseAll = () => {
      for (const id of [...pressed.keys()]) release(id)
    }

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target
      if (target instanceof Element && target.closest(TOASTER_SELECTOR)) {
        pressed.set(event.pointerId, target)
      }
    }
    const onPointerUp = (event: PointerEvent) => {
      pressed.delete(event.pointerId)
    }
    const onPointerCancel = (event: PointerEvent) => {
      release(event.pointerId)
    }

    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('pointerup', onPointerUp, true)
    document.addEventListener('pointercancel', onPointerCancel, true)
    // iOS may background the app mid-gesture without firing pointercancel.
    document.addEventListener('visibilitychange', releaseAll)
    window.addEventListener('pagehide', releaseAll)
    window.addEventListener('blur', releaseAll)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('pointerup', onPointerUp, true)
      document.removeEventListener('pointercancel', onPointerCancel, true)
      document.removeEventListener('visibilitychange', releaseAll)
      window.removeEventListener('pagehide', releaseAll)
      window.removeEventListener('blur', releaseAll)
    }
  }, [])
}

export function AppToaster({
  aboveTabBar,
  theme,
}: {
  /** True when the mobile BottomTabBar is mounted. */
  aboveTabBar: boolean
  theme?: ToasterProps['theme']
}) {
  useReleaseCancelledToastPresses()
  return (
    <Toaster
      position="bottom-right"
      theme={theme}
      richColors
      offset={{ bottom: aboveTabBar ? ABOVE_TAB_BAR : 'calc(24px + var(--sab))' }}
      mobileOffset={{ bottom: aboveTabBar ? ABOVE_TAB_BAR : 'calc(16px + var(--sab))' }}
    />
  )
}
