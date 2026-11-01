import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LibraryViewControls } from '@/components/library/LibraryViewControls'

type Props = React.ComponentProps<typeof LibraryViewControls>

function setup(overrides: Partial<Props> = {}) {
  const props: Props = {
    viewMode: 'grid',
    onViewModeChange: vi.fn(),
    density: 'comfortable',
    densityOverridden: false,
    onDensityChange: vi.fn(),
    onFollowSettings: vi.fn(),
    onMenuOpenChange: vi.fn(),
    ...overrides,
  }
  const view = render(<LibraryViewControls {...props} />)
  return { props, view }
}

describe('LibraryViewControls', () => {
  it('test_menu_is_not_rendered_before_first_open', () => {
    setup()

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('radio', { name: 'Compact' })).toBeNull()
    expect(screen.getByTestId('library-view-menu-button')).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('test_inline_layout_radiogroup_marks_the_active_mode_and_switches', () => {
    const { props } = setup({ viewMode: 'grid' })

    const inline = screen.getByTestId('library-view-inline')
    expect(inline).toHaveAttribute('role', 'radiogroup')
    expect(within(inline).getByRole('radio', { name: 'Grid view' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    const list = within(inline).getByRole('radio', { name: 'List view' })
    expect(list).toHaveAttribute('aria-checked', 'false')

    fireEvent.click(list)
    expect(props.onViewModeChange).toHaveBeenCalledWith('list')
  })

  it('test_density_button_is_absent_in_list_mode', () => {
    const { view, props } = setup({ viewMode: 'list' })
    expect(screen.queryByTestId('library-density-button')).toBeNull()

    view.rerender(<LibraryViewControls {...props} viewMode="grid" />)
    expect(screen.getByTestId('library-density-button')).toBeInTheDocument()
  })

  it('test_view_button_menu_offers_layout_and_density_and_reports_open_state', async () => {
    const { props } = setup()

    fireEvent.click(screen.getByTestId('library-view-menu-button'))
    const dialog = await screen.findByRole('dialog')

    expect(props.onMenuOpenChange).toHaveBeenLastCalledWith(true)
    expect(screen.getByTestId('library-view-menu-button')).toHaveAttribute('aria-expanded', 'true')
    // Layout radiogroup only when opened from the View button.
    expect(within(dialog).getByRole('radio', { name: 'Grid view' })).toBeInTheDocument()
    expect(within(dialog).getByRole('radio', { name: 'List view' })).toBeInTheDocument()
    expect(within(dialog).getByRole('radio', { name: 'Comfortable' })).toHaveAttribute(
      'aria-checked',
      'true',
    )

    fireEvent.click(within(dialog).getByRole('radio', { name: 'Compact' }))
    expect(props.onDensityChange).toHaveBeenCalledWith('compact')
  })

  it('test_density_button_menu_has_no_layout_radiogroup', async () => {
    setup()

    fireEvent.click(screen.getByTestId('library-density-button'))
    const dialog = await screen.findByRole('dialog')

    expect(within(dialog).getByRole('radio', { name: 'Spacious' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('radio', { name: 'Grid view' })).toBeNull()
    expect(within(dialog).queryByRole('radio', { name: 'List view' })).toBeNull()
  })

  it('test_list_mode_view_menu_has_layout_but_no_density_options', async () => {
    setup({ viewMode: 'list' })

    fireEvent.click(screen.getByTestId('library-view-menu-button'))
    const dialog = await screen.findByRole('dialog')

    expect(within(dialog).getByRole('radio', { name: 'List view' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('radio', { name: 'Compact' })).toBeNull()
  })

  it('test_follow_settings_is_offered_only_while_the_density_is_overridden', async () => {
    const { view, props } = setup({ densityOverridden: false })
    fireEvent.click(screen.getByTestId('library-density-button'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByText('Follow settings')).toBeNull()

    view.rerender(<LibraryViewControls {...props} densityOverridden />)
    const follow = within(await screen.findByRole('dialog')).getByText('Follow settings')
    fireEvent.click(follow)
    expect(props.onFollowSettings).toHaveBeenCalledTimes(1)
  })

  it('test_pressing_a_control_does_not_move_focus_to_it', () => {
    // The search block locks its reveal while it holds focus.
    setup()
    for (const id of ['library-view-menu-button', 'library-density-button']) {
      const notPrevented = fireEvent.mouseDown(screen.getByTestId(id))
      expect(notPrevented).toBe(false)
    }
    const radio = within(screen.getByTestId('library-view-inline')).getByRole('radio', {
      name: 'List view',
    })
    expect(fireEvent.mouseDown(radio)).toBe(false)
  })

  it('test_closing_the_menu_reports_closed_to_the_search_block', async () => {
    const { props } = setup()
    fireEvent.click(screen.getByTestId('library-view-menu-button'))
    await screen.findByRole('dialog')

    await act(async () => {
      fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
    })

    expect(props.onMenuOpenChange).toHaveBeenLastCalledWith(false)
  })
})
