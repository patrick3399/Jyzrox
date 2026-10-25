import { afterEach, describe, expect, it } from 'vitest'
import { detailHotkey } from '@/lib/detailHotkeys'

/** Dispatch a real keydown so `event.target` is resolved the way the browser does. */
function keydownOn(
  target: EventTarget,
  key: string,
  init: KeyboardEventInit = {},
): KeyboardEvent {
  let captured: KeyboardEvent | null = null
  const listener = (event: Event) => {
    captured = event as KeyboardEvent
  }
  window.addEventListener('keydown', listener)
  try {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))
  } finally {
    window.removeEventListener('keydown', listener)
  }
  if (!captured) throw new Error('keydown did not reach window')
  return captured
}

function mount<T extends HTMLElement>(html: string, selector: string): T {
  document.body.innerHTML = html
  const el = document.body.querySelector<T>(selector)
  if (!el) throw new Error(`missing ${selector}`)
  return el
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('detailHotkey — what the page maps', () => {
  it('maps Enter and Space on the body to open', () => {
    expect(detailHotkey(keydownOn(document.body, 'Enter'))).toBe('open')
    expect(detailHotkey(keydownOn(document.body, ' '))).toBe('open')
  })

  it('maps Escape and ArrowUp on the body to back', () => {
    expect(detailHotkey(keydownOn(document.body, 'Escape'))).toBe('back')
    expect(detailHotkey(keydownOn(document.body, 'ArrowUp'))).toBe('back')
  })

  it('treats window/document targets as not interactive', () => {
    expect(detailHotkey(keydownOn(window, 'Enter'))).toBe('open')
    expect(detailHotkey(keydownOn(document, 'Escape'))).toBe('back')
  })

  it('ignores unrelated keys', () => {
    expect(detailHotkey(keydownOn(document.body, 'a'))).toBeNull()
    expect(detailHotkey(keydownOn(document.body, 'ArrowDown'))).toBeNull()
    expect(detailHotkey(keydownOn(document.body, 'Tab'))).toBeNull()
  })
})

describe('detailHotkey — modifiers, IME and handled events', () => {
  it.each(['altKey', 'ctrlKey', 'metaKey', 'shiftKey'] as const)(
    'returns null when %s is held',
    (modifier) => {
      expect(detailHotkey(keydownOn(document.body, 'Enter', { [modifier]: true }))).toBeNull()
      expect(detailHotkey(keydownOn(document.body, 'Escape', { [modifier]: true }))).toBeNull()
    },
  )

  it('returns null while an IME composition is active', () => {
    expect(detailHotkey(keydownOn(document.body, 'Enter', { isComposing: true }))).toBeNull()
    expect(detailHotkey(keydownOn(document.body, 'Escape', { isComposing: true }))).toBeNull()
  })

  it('returns null when an earlier handler already called preventDefault', () => {
    const early = (event: Event) => event.preventDefault()
    document.addEventListener('keydown', early)
    try {
      expect(detailHotkey(keydownOn(document.body, 'Escape'))).toBeNull()
      expect(detailHotkey(keydownOn(document.body, 'Enter'))).toBeNull()
    } finally {
      document.removeEventListener('keydown', early)
    }
  })
})

describe('detailHotkey — Enter/Space leave activatable and text-entry targets alone', () => {
  const blockers: Array<[string, string, string]> = [
    ['link with href', '<a href="/x"><span id="t">go</span></a>', '#t'],
    ['button', '<button id="t">b</button>', '#t'],
    ['element inside a button', '<button><svg><circle id="t"></circle></svg></button>', '#t'],
    ['input', '<input id="t" />', '#t'],
    ['select', '<select id="t"><option>1</option></select>', '#t'],
    ['textarea', '<textarea id="t"></textarea>', '#t'],
    ['summary', '<details><summary id="t">s</summary></details>', '#t'],
    ['contenteditable', '<div contenteditable="true" id="t"></div>', '#t'],
    ['contenteditable (empty attr)', '<div contenteditable="" id="t"></div>', '#t'],
    ['role=button', '<div role="button" id="t"></div>', '#t'],
    ['role=link', '<div role="link" id="t"></div>', '#t'],
    ['role=menuitem', '<div role="menuitem" id="t"></div>', '#t'],
    ['role=option', '<div role="option" id="t"></div>', '#t'],
    ['role=tab', '<div role="tab" id="t"></div>', '#t'],
    ['role=checkbox', '<div role="checkbox" id="t"></div>', '#t'],
    ['role=switch', '<div role="switch" id="t"></div>', '#t'],
    ['role=textbox', '<div role="textbox" id="t"></div>', '#t'],
    ['role=combobox', '<div role="combobox" id="t"></div>', '#t'],
  ]

  it.each(blockers)('returns null for Enter and Space on a %s', (_name, html, selector) => {
    const el = mount(html, selector)
    expect(detailHotkey(keydownOn(el, 'Enter'))).toBeNull()
    expect(detailHotkey(keydownOn(el, ' '))).toBeNull()
  })

  it('still opens for an anchor without href (not activatable)', () => {
    const el = mount('<a id="t">x</a>', '#t')
    expect(detailHotkey(keydownOn(el, 'Enter'))).toBe('open')
  })

  it('still opens for contenteditable="false"', () => {
    const el = mount('<div contenteditable="false" id="t"></div>', '#t')
    expect(detailHotkey(keydownOn(el, 'Enter'))).toBe('open')
  })

  it('still opens for a plain div', () => {
    const el = mount('<div id="t"></div>', '#t')
    expect(detailHotkey(keydownOn(el, ' '))).toBe('open')
  })
})

describe('detailHotkey — Escape/ArrowUp leave text-entry targets alone but not buttons', () => {
  const textEntry: Array<[string, string, string]> = [
    ['input', '<input id="t" />', '#t'],
    ['select', '<select id="t"><option>1</option></select>', '#t'],
    ['textarea', '<textarea id="t"></textarea>', '#t'],
    ['contenteditable', '<div contenteditable="true" id="t"></div>', '#t'],
    ['element inside contenteditable', '<div contenteditable="true"><b id="t">x</b></div>', '#t'],
    ['role=textbox', '<div role="textbox" id="t"></div>', '#t'],
    ['role=combobox', '<div role="combobox" id="t"></div>', '#t'],
    ['role=listbox', '<div role="listbox" id="t"></div>', '#t'],
  ]

  it.each(textEntry)('returns null for Escape and ArrowUp on a %s', (_name, html, selector) => {
    const el = mount(html, selector)
    expect(detailHotkey(keydownOn(el, 'Escape'))).toBeNull()
    expect(detailHotkey(keydownOn(el, 'ArrowUp'))).toBeNull()
  })

  // After clicking any control focus stays on it; Esc must still go back.
  it.each([
    ['button', '<button id="t">b</button>'],
    ['link', '<a href="/x" id="t">l</a>'],
    ['role=button', '<div role="button" id="t"></div>'],
    ['summary', '<details><summary id="t">s</summary></details>'],
  ])('still goes back for Escape and ArrowUp while a %s has focus', (_name, html) => {
    const el = mount(html, '#t')
    expect(detailHotkey(keydownOn(el, 'Escape'))).toBe('back')
    expect(detailHotkey(keydownOn(el, 'ArrowUp'))).toBe('back')
  })

  it('goes back for contenteditable="false"', () => {
    const el = mount('<div contenteditable="false" id="t"></div>', '#t')
    expect(detailHotkey(keydownOn(el, 'Escape'))).toBe('back')
  })
})
