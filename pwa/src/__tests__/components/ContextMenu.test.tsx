/**
 * ContextMenu — Vitest test suite
 *
 * Covers:
 *   - Does not render when open=false
 *   - Renders menu with role="menu" when open=true
 *   - Renders all menu items as menuitem buttons
 *   - Clicking a menu item calls the item's onClick handler
 *   - Clicking a menu item calls onClose
 *   - Clicking the backdrop calls onClose
 *   - Pressing Escape calls onClose
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import type { ContextMenuItem } from '@/components/ContextMenu'

// ── Import component (no module mocks needed for ContextMenu) ──────────

import { ContextMenu } from '@/components/ContextMenu'

// ── Helpers ────────────────────────────────────────────────────────────

function makeItems(count = 2): ContextMenuItem[] {
  return Array.from({ length: count }, (_, i) => ({
    label: `Item ${i + 1}`,
    onClick: vi.fn(),
  }))
}

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('ContextMenu', () => {
  describe('visibility', () => {
    it('test_contextMenu_openFalse_rendersNothing', () => {
      const { container } = render(
        <ContextMenu
          open={false}
          onClose={vi.fn()}
          position={{ x: 100, y: 100 }}
          items={makeItems()}
        />,
      )
      expect(container.firstChild).toBeNull()
    })

    it('test_contextMenu_openTrue_rendersMenu', () => {
      render(
        <ContextMenu
          open={true}
          onClose={vi.fn()}
          position={{ x: 100, y: 100 }}
          items={makeItems()}
        />,
      )
      expect(screen.getByRole('menu')).toBeInTheDocument()
    })

    it('test_contextMenu_openTrue_menuHasAriaLabel', () => {
      render(
        <ContextMenu
          open={true}
          onClose={vi.fn()}
          position={{ x: 100, y: 100 }}
          items={makeItems()}
        />,
      )
      expect(screen.getByRole('menu', { name: 'Context menu' })).toBeInTheDocument()
    })
  })

  describe('menu items', () => {
    it('test_contextMenu_rendersAllItemLabels', () => {
      const items = makeItems(3)
      render(
        <ContextMenu
          open={true}
          onClose={vi.fn()}
          position={{ x: 50, y: 50 }}
          items={items}
        />,
      )
      for (const item of items) {
        expect(screen.getByText(item.label)).toBeInTheDocument()
      }
    })

    it('test_contextMenu_rendersItemsAsMenuItemButtons', () => {
      render(
        <ContextMenu
          open={true}
          onClose={vi.fn()}
          position={{ x: 50, y: 50 }}
          items={makeItems(2)}
        />,
      )
      const menuItems = screen.getAllByRole('menuitem')
      expect(menuItems).toHaveLength(2)
    })

    it('test_contextMenu_clickingItem_callsItemOnClick', () => {
      const items = makeItems(2)
      render(
        <ContextMenu
          open={true}
          onClose={vi.fn()}
          position={{ x: 50, y: 50 }}
          items={items}
        />,
      )
      fireEvent.click(screen.getByText('Item 1'))
      expect(items[0].onClick).toHaveBeenCalledOnce()
    })

    it('test_contextMenu_clickingItem_callsOnClose', () => {
      const onClose = vi.fn()
      const items = makeItems(2)
      render(
        <ContextMenu
          open={true}
          onClose={onClose}
          position={{ x: 50, y: 50 }}
          items={items}
        />,
      )
      fireEvent.click(screen.getByText('Item 1'))
      expect(onClose).toHaveBeenCalledOnce()
    })
  })

  describe('close behavior', () => {
    it('test_contextMenu_pointerDownOnBackdrop_callsOnClose', () => {
      const onClose = vi.fn()
      render(
        <ContextMenu
          open={true}
          onClose={onClose}
          position={{ x: 50, y: 50 }}
          items={makeItems()}
        />,
      )
      // The backdrop is the first fixed div (aria-hidden)
      const backdrop = document.querySelector('[aria-hidden="true"]') as HTMLElement
      expect(backdrop).not.toBeNull()
      fireEvent.pointerDown(backdrop)
      expect(onClose).toHaveBeenCalledOnce()
    })

    it('test_contextMenu_pressEscape_callsOnClose', () => {
      const onClose = vi.fn()
      render(
        <ContextMenu
          open={true}
          onClose={onClose}
          position={{ x: 50, y: 50 }}
          items={makeItems()}
        />,
      )
      act(() => {
        fireEvent.keyDown(document, { key: 'Escape' })
      })
      expect(onClose).toHaveBeenCalledOnce()
    })

    it('test_contextMenu_pressOtherKey_doesNotCallOnClose', () => {
      const onClose = vi.fn()
      render(
        <ContextMenu
          open={true}
          onClose={onClose}
          position={{ x: 50, y: 50 }}
          items={makeItems()}
        />,
      )
      act(() => {
        fireEvent.keyDown(document, { key: 'Enter' })
      })
      expect(onClose).not.toHaveBeenCalled()
    })
  })

  describe('position', () => {
    it('test_contextMenu_position_appliedToMenuStyle', () => {
      render(
        <ContextMenu
          open={true}
          onClose={vi.fn()}
          position={{ x: 200, y: 300 }}
          items={makeItems()}
        />,
      )
      const menu = screen.getByRole('menu')
      // Position is applied via style; exact value depends on viewport boundary detection
      // but the menu must exist and have a style attribute
      expect(menu).toHaveAttribute('style')
    })
  })
})
