import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Dialog } from '@/components/ui/dialog'
import { AlertDialog } from '@/components/ui/alert-dialog'

const windowEsc = vi.fn()
function listenOnWindow() {
  window.addEventListener('keydown', windowEsc)
}
afterEach(() => {
  window.removeEventListener('keydown', windowEsc)
  windowEsc.mockReset()
})

function pressEscape(): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  act(() => {
    ;(document.activeElement ?? document.body).dispatchEvent(event)
  })
  return event
}

describe('Dialog', () => {
  it('claims Escape: closes, preventDefault, and never reaches a window listener (FE-T25)', () => {
    listenOnWindow()
    const onOpenChange = vi.fn()
    render(<Dialog open onOpenChange={onOpenChange} title="T">body</Dialog>)
    const event = pressEscape()
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(event.defaultPrevented).toBe(true)
    expect(windowEsc).not.toHaveBeenCalled()
  })

  it('ignores Escape and the close button while not dismissible (busy)', () => {
    listenOnWindow()
    const onOpenChange = vi.fn()
    render(<Dialog open onOpenChange={onOpenChange} title="T" dismissible={false}>body</Dialog>)
    const event = pressEscape()
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(true)
    expect(windowEsc).not.toHaveBeenCalled()
    expect((screen.getByRole('button', { name: 'Close' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('labels the dialog with its title and renders the footer', () => {
    render(<Dialog open onOpenChange={() => {}} title="Rename" footer={<button>Save</button>}>x</Dialog>)
    expect(screen.getByRole('dialog', { name: 'Rename' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Save' })).toBeTruthy()
  })
})

describe('AlertDialog', () => {
  it('confirms once and disables both buttons while busy', () => {
    const onConfirm = vi.fn()
    const { rerender } = render(
      <AlertDialog open onOpenChange={() => {}} title="Delete?" confirmLabel="Delete" onConfirm={onConfirm} destructive />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    rerender(<AlertDialog open onOpenChange={() => {}} title="Delete?" confirmLabel="Delete" onConfirm={onConfirm} destructive busy />)
    expect((screen.getByRole('button', { name: 'Delete' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
