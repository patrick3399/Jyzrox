import { readFileSync } from 'node:fs'
import path from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ContextMenu } from '@/components/ContextMenu'

const SRC = path.resolve(__dirname, '..')
const read = (rel: string) => readFileSync(path.join(SRC, rel), 'utf8')

function staticallyImports(source: string, specifier: string): boolean {
  const escaped = specifier.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')
  return new RegExp(`^import\\s[^;]*?from\\s+['"]${escaped}['"]`, 'm').test(source)
}

// Base UI Menu/Dialog and their positioner added ~64 kB gzip to /library when
// gallery cards and the batch bar imported them eagerly. They load on first open.
describe('Library overlays load on demand', () => {
  it('test_gallery_card_context_menu_does_not_statically_import_base_ui_menu', () => {
    const src = read('components/ContextMenu.tsx')
    expect(staticallyImports(src, '@/components/ui/menu')).toBe(false)
    expect(staticallyImports(src, './ui/menu')).toBe(false)
  })

  it('test_library_page_does_not_statically_import_dialog_or_collection_menu', () => {
    const src = read('app/library/page.tsx')
    expect(staticallyImports(src, '@/components/ui/dialog')).toBe(false)
    expect(staticallyImports(src, '@/components/library/AddToCollectionMenu')).toBe(false)
  })

  it('test_context_menu_renders_nothing_until_first_opened_then_shows_menu', async () => {
    const items = [{ label: 'Open', onClick: vi.fn() }]
    const { rerender } = render(
      <ContextMenu open={false} onClose={() => {}} position={{ x: 0, y: 0 }} items={items} />,
    )
    expect(screen.queryByRole('menu')).toBeNull()
    rerender(<ContextMenu open onClose={() => {}} position={{ x: 0, y: 0 }} items={items} />)
    expect(await screen.findByRole('menu')).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: 'Open' })).toBeTruthy()
  })
})
