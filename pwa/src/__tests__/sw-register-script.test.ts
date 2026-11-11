import { createContext, runInContext } from 'node:vm'
import { describe, expect, it } from 'vitest'
import { SW_REGISTER_SCRIPT } from '@/lib/swRegisterScript'

/**
 * Run the inline registration script the way the root layout ships it, with the
 * document already at the given readyState, then fire `load` if the page has
 * not reached it yet. Returns how many times register('/sw.js') was called.
 */
function runRegisterScript(readyState: DocumentReadyState, { fireLoad }: { fireLoad: boolean }) {
  const registered: string[] = []
  const loadListeners: Array<() => void> = []
  const sandbox = {
    document: { readyState },
    window: {
      addEventListener: (type: string, fn: () => void) => {
        if (type === 'load') loadListeners.push(fn)
      },
    },
    navigator: {
      serviceWorker: {
        register: (url: string) => {
          registered.push(url)
          return Promise.resolve()
        },
      },
    },
    console,
  }
  createContext(sandbox)
  runInContext(SW_REGISTER_SCRIPT, sandbox)
  if (fireLoad) loadListeners.forEach((fn) => fn())
  return registered
}

describe('service worker registration script', () => {
  it('registers when the script runs after the load event has already fired', () => {
    // Regression: the script is injected `afterInteractive`, i.e. after
    // hydration, and only then waited for `load`. On a fast page `load` had
    // already fired, so the listener never ran and fresh devices never got a
    // service worker (no offline page, no offline share queue).
    expect(runRegisterScript('complete', { fireLoad: false })).toEqual(['/sw.js'])
  })

  it('still defers registration to the load event while the page is loading', () => {
    expect(runRegisterScript('interactive', { fireLoad: false })).toEqual([])
    expect(runRegisterScript('interactive', { fireLoad: true })).toEqual(['/sw.js'])
  })

  it('does nothing in browsers without service worker support', () => {
    const sandbox = {
      document: { readyState: 'complete' },
      window: { addEventListener: () => {} },
      navigator: {},
      console,
    }
    createContext(sandbox)
    expect(() => runInContext(SW_REGISTER_SCRIPT, sandbox)).not.toThrow()
  })
})
