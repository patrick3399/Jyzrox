import { readFileSync } from 'node:fs'
import path from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render } from '@testing-library/react'
import { toast } from 'sonner'
import { AppToaster } from '@/components/AppToaster'

// jsdom has no pointer capture; sonner calls setPointerCapture on pointerdown.
beforeAll(() => {
  Element.prototype.setPointerCapture ??= function () {}
  Element.prototype.releasePointerCapture ??= function () {}
  Element.prototype.hasPointerCapture ??= function () {
    return false
  }
})

let hidden = false
Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })

afterEach(() => {
  act(() => {
    toast.dismiss()
    vi.advanceTimersByTime(1000)
  })
  hidden = false
  vi.useRealTimers()
})

const toastCount = () => document.querySelectorAll('[data-sonner-toast]').length

function showToast(aboveTabBar = true) {
  vi.useFakeTimers()
  render(<AppToaster aboveTabBar={aboveTabBar} />)
  act(() => {
    toast('Subscribed', { duration: 1000 })
  })
  act(() => {
    vi.advanceTimersByTime(50)
  })
  expect(toastCount()).toBe(1)
  return document.querySelector('[data-sonner-toast]') as HTMLElement
}

function setHidden(value: boolean) {
  hidden = value
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

describe('AppToaster', () => {
  it('still auto-dismisses after a pointercancel on the toast (OS gesture took the touch)', () => {
    // Swiping up from the home indicator starts on a bottom toast; the OS then
    // cancels the pointer, so sonner never sees pointerup and its "interacting"
    // flag pauses every toast forever.
    const el = showToast()
    fireEvent.pointerDown(el, { pointerId: 7 })
    fireEvent.pointerCancel(el, { pointerId: 7 })
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(toastCount()).toBe(0)
  })

  it('still auto-dismisses when the page is hidden mid-press without any pointerup or pointercancel', () => {
    const el = showToast()
    fireEvent.pointerDown(el, { pointerId: 3 })
    setHidden(true)
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    setHidden(false)
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(toastCount()).toBe(0)
  })

  it('keeps the timer paused while a press on the toast is still in progress', () => {
    const el = showToast()
    fireEvent.pointerDown(el, { pointerId: 1 })
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(toastCount()).toBe(1)
    fireEvent.pointerUp(el, { pointerId: 1 })
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(toastCount()).toBe(0)
  })

  it('stacks toasts above the bottom tab bar instead of over it', () => {
    showToast(true)
    const list = document.querySelector('[data-sonner-toaster]') as HTMLElement
    expect(list.style.getPropertyValue('--mobile-offset-bottom')).toBe('var(--toast-offset-bottom)')
    expect(list.style.getPropertyValue('--offset-bottom')).toBe('var(--toast-offset-bottom)')

    const css = readFileSync(path.resolve(__dirname, '../../app/globals.css'), 'utf8')
    // BottomTabBar is calc(4rem + var(--sab)) tall and lg:hidden.
    expect(css).toMatch(/--toast-offset-bottom:\s*calc\(4rem \+ var\(--sab\) \+ [^)]+\)/)
    expect(css).toMatch(/@media \(min-width: 1024px\)\s*\{\s*:root\s*\{\s*--toast-offset-bottom:/)
  })

  it('keeps toasts clear of the home indicator when there is no tab bar', () => {
    showToast(false)
    const list = document.querySelector('[data-sonner-toaster]') as HTMLElement
    expect(list.style.getPropertyValue('--mobile-offset-bottom')).toContain('var(--sab)')
  })
})
