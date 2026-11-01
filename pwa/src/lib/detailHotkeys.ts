export type DetailHotkey = 'open' | 'back'

// Elements that already own Enter/Space (activation, text entry, menus).
const OPEN_BLOCKERS = [
  'a[href]',
  'button',
  'input',
  'select',
  'textarea',
  'summary',
  '[contenteditable]:not([contenteditable="false"])',
  '[role="button"]',
  '[role="link"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[role="tab"]',
  '[role="checkbox"]',
  '[role="switch"]',
  '[role="textbox"]',
  '[role="combobox"]',
].join(',')

// Escape/ArrowUp only belong to text entry and pickers. A plain button does
// not own them, and after clicking anything focus stays on that button.
const BACK_BLOCKERS = [
  'input',
  'select',
  'textarea',
  '[contenteditable]:not([contenteditable="false"])',
  '[role="textbox"]',
  '[role="combobox"]',
  '[role="listbox"]',
].join(',')

function targetMatches(target: EventTarget | null, selector: string): boolean {
  // window/document targets (and text nodes) are not interactive elements.
  if (typeof Element === 'undefined' || !(target instanceof Element)) return false
  return target.closest(selector) !== null
}

/** Classify a window keydown for a detail page's page-level shortcuts (Enter/Space open the reader, Escape/ArrowUp go back), or null when the page must leave the key alone. */
export function detailHotkey(event: KeyboardEvent): DetailHotkey | null {
  if (event.defaultPrevented || event.isComposing) return null
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return null

  if (event.key === 'Enter' || event.key === ' ') {
    return targetMatches(event.target, OPEN_BLOCKERS) ? null : 'open'
  }
  if (event.key === 'Escape' || event.key === 'ArrowUp') {
    return targetMatches(event.target, BACK_BLOCKERS) ? null : 'back'
  }
  return null
}
