/**
 * The anchor of the view menu is not a Base UI Trigger, so on touch the popover
 * counts a tap on the anchor as an outside press and closes on pointer-down; the
 * click that follows must not reopen it. The stub menu below exposes the
 * popover's `onOpenChange` so the test can play that dismissal.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const menu = vi.hoisted(() => ({
  onOpenChange: null as null | ((open: boolean) => void),
  open: false,
}))

vi.mock('@/components/library/LibraryViewMenu', () => ({
  LibraryViewMenu: (props: { open: boolean; onOpenChange: (open: boolean) => void }) => {
    menu.onOpenChange = props.onOpenChange
    menu.open = props.open
    return <div data-testid="stub-menu" data-open={String(props.open)} />
  },
}))

import { LibraryViewControls } from '@/components/library/LibraryViewControls'

const noop = () => {}

function renderControls(onMenuOpenChange = vi.fn()) {
  render(
    <LibraryViewControls
      viewMode="grid"
      onViewModeChange={noop}
      density="comfortable"
      densityOverridden={false}
      onDensityChange={noop}
      onFollowSettings={noop}
      onMenuOpenChange={onMenuOpenChange}
    />,
  )
  return onMenuOpenChange
}

/** One tap: pointerdown, (optional outside-press dismissal), then click. */
function tap(button: HTMLElement, dismissOnPress: boolean) {
  fireEvent.pointerDown(button)
  if (dismissOnPress) act(() => menu.onOpenChange?.(false))
  fireEvent.click(button)
}

beforeEach(() => {
  menu.onOpenChange = null
  menu.open = false
})

describe('LibraryViewControls menu toggle', () => {
  it('test_second_tap_on_the_anchor_closes_the_menu_and_the_click_does_not_reopen_it', async () => {
    const onMenuOpenChange = renderControls()
    const button = screen.getByTestId('library-view-menu-button')

    tap(button, false)
    expect(await screen.findByTestId('stub-menu')).toHaveAttribute('data-open', 'true')
    expect(button).toHaveAttribute('aria-expanded', 'true')

    // Second tap: pointer-down dismisses (outside press), then click arrives.
    tap(button, true)

    expect(screen.getByTestId('stub-menu')).toHaveAttribute('data-open', 'false')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(onMenuOpenChange).toHaveBeenLastCalledWith(false)
  })

  it('test_second_tap_on_the_density_button_stays_closed_after_dismissal', async () => {
    renderControls()
    const button = screen.getByTestId('library-density-button')

    tap(button, false)
    expect(await screen.findByTestId('stub-menu')).toHaveAttribute('data-open', 'true')
    tap(button, true)

    expect(screen.getByTestId('stub-menu')).toHaveAttribute('data-open', 'false')
  })

  it('test_a_tap_after_the_menu_closed_reopens_it', async () => {
    renderControls()
    const button = screen.getByTestId('library-view-menu-button')
    tap(button, false)
    await screen.findByTestId('stub-menu')
    tap(button, true)
    expect(screen.getByTestId('stub-menu')).toHaveAttribute('data-open', 'false')

    tap(button, false)

    expect(screen.getByTestId('stub-menu')).toHaveAttribute('data-open', 'true')
  })

  it('test_mouse_click_without_pointerdown_still_toggles', async () => {
    // Keyboard activation fires click with no pointer events.
    renderControls()
    const button = screen.getByTestId('library-view-menu-button')

    fireEvent.click(button)
    expect(await screen.findByTestId('stub-menu')).toHaveAttribute('data-open', 'true')
    fireEvent.click(button)
    expect(screen.getByTestId('stub-menu')).toHaveAttribute('data-open', 'false')
  })
})
