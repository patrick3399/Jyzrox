import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AnchoredMenu } from '@/components/ui/menu'
import { Popover } from '@/components/ui/popover'

const windowEsc = vi.fn()
afterEach(() => {
  window.removeEventListener('keydown', windowEsc)
  windowEsc.mockReset()
})

function pressEscape() {
  window.addEventListener('keydown', windowEsc)
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  act(() => {
    ;(document.activeElement ?? document.body).dispatchEvent(event)
  })
  return event
}

describe('AnchoredMenu', () => {
  it('runs the selected entry once and closes', () => {
    const onSelect = vi.fn()
    const onOpenChange = vi.fn()
    render(<AnchoredMenu open onOpenChange={onOpenChange} x={10} y={10} ariaLabel="m" items={[{ id: 'a', label: 'Open', onSelect }]} />)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Open' }))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('does not run a disabled entry', () => {
    const onSelect = vi.fn()
    render(<AnchoredMenu open onOpenChange={() => {}} x={0} y={0} ariaLabel="m" items={[{ id: 'a', label: 'Nope', disabled: true, onSelect }]} />)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Nope' }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('claims Escape (FE-T25)', () => {
    const onOpenChange = vi.fn()
    render(<AnchoredMenu open onOpenChange={onOpenChange} x={0} y={0} ariaLabel="m" items={[{ id: 'a', label: 'A', onSelect: () => {} }]} />)
    const event = pressEscape()
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(event.defaultPrevented).toBe(true)
    expect(windowEsc).not.toHaveBeenCalled()
  })
})

describe('Popover', () => {
  it('claims Escape (FE-T25)', () => {
    const anchor = document.createElement('button')
    document.body.appendChild(anchor)
    const onOpenChange = vi.fn()
    render(<Popover open onOpenChange={onOpenChange} anchor={anchor} ariaLabel="p"><p>content</p></Popover>)
    expect(screen.getByText('content')).toBeTruthy()
    const event = pressEscape()
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(event.defaultPrevented).toBe(true)
    expect(windowEsc).not.toHaveBeenCalled()
    anchor.remove()
  })
})
