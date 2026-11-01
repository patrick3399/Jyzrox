/**
 * Regression: the image context menu closed on a document-level Escape without
 * marking the event handled. The Library detail page reads the same Escape on
 * window as "go back", and in a browser React commits the close (and re-binds
 * the page's listener without the menu) before the event reaches window — so
 * closing the menu also left the page. `detailHotkey()` skips handled events.
 *
 * The menu does not stop propagation: the Reader's own Escape exit is out of
 * scope here and keeps seeing the key.
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { ImageContextMenu } from '@/components/Reader/ImageContextMenu'

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

function renderMenu(onClose: () => void) {
  return render(
    <ImageContextMenu
      open
      onClose={onClose}
      position={{ x: 10, y: 10 }}
      imageUrl="/media/a.jpg"
    />,
  )
}

describe('Escape while the image context menu is open', () => {
  it('closes the menu and marks the Escape as handled for window-level shortcuts', () => {
    const onClose = vi.fn()
    renderMenu(onClose)
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })

    fireEvent(document.body, event)

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
  })

  it('leaves other keys unhandled', () => {
    const onClose = vi.fn()
    renderMenu(onClose)
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })

    fireEvent(document.body, event)

    expect(onClose).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
  })
})
