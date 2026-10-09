/**
 * Settings > Gallery Categories (admin) — Vitest suite
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const { mockGuard, mockRegistry, mockCreate, mockUpdateColor, mockRemove, mockBackfill, mockMutate } =
  vi.hoisted(() => ({
    mockGuard: vi.fn(),
    mockRegistry: vi.fn(),
    mockCreate: vi.fn(),
    mockUpdateColor: vi.fn(),
    mockRemove: vi.fn(),
    mockBackfill: vi.fn(),
    mockMutate: vi.fn(),
  }))

vi.mock('@/hooks/useAdminGuard', () => ({ useAdminGuard: () => mockGuard() }))
vi.mock('@/hooks/useCategoryRegistry', () => ({ useCategoryRegistry: () => mockRegistry() }))
vi.mock('@/lib/api', () => ({
  api: {
    galleryCategories: {
      create: mockCreate,
      updateColor: mockUpdateColor,
      remove: mockRemove,
      backfill: mockBackfill,
    },
  },
}))
vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('swr', () => ({ useSWRConfig: () => ({ mutate: vi.fn() }) }))
vi.mock('@/components/BackButton', () => ({ BackButton: () => null }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

import CategoriesSettingsPage from '@/app/settings/categories/page'
import { getVisibleCategories } from '@/lib/settingsRegistry'

const data = {
  categories: [
    { id: 1, name: 'Cosplay', color: 'red', sort_order: 8, is_builtin: true, gallery_count: 3 },
    { id: 11, name: 'Novel', color: 'teal', sort_order: 11, is_builtin: false, gallery_count: 7 },
  ],
  palette: ['red', 'teal', 'gray'],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGuard.mockReturnValue(true)
  mockRegistry.mockReturnValue({ data, mutate: mockMutate, isLoading: false })
  mockCreate.mockResolvedValue({})
  mockRemove.mockResolvedValue({ deleted: 'Novel', galleries_cleared: 7 })
  mockBackfill.mockResolvedValue({ dry_run: true, matched: 4, applied: 0 })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CategoriesSettingsPage', () => {
  it('test_categories_page_non_admin_renders_nothing', () => {
    mockGuard.mockReturnValue(false)
    const { container } = render(<CategoriesSettingsPage />)
    expect(container.innerHTML).toBe('')
  })

  it('test_categories_page_lists_builtin_and_custom_with_gallery_count', () => {
    render(<CategoriesSettingsPage />)
    expect(screen.getByText('Cosplay')).toBeInTheDocument()
    expect(screen.getByText('Novel')).toBeInTheDocument()
    expect(screen.getByText('categories.galleryCount:{"count":"7"}')).toBeInTheDocument()
  })

  it('test_categories_page_add_calls_create_with_name_and_color', async () => {
    render(<CategoriesSettingsPage />)
    fireEvent.change(screen.getByPlaceholderText('categories.namePlaceholder'), {
      target: { value: '  Comic ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'categories.add' }))
    await waitFor(() => expect(mockCreate).toHaveBeenCalledWith({ name: 'Comic', color: 'gray' }))
  })

  it('test_categories_page_delete_confirmed_calls_remove', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CategoriesSettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'categories.delete' }))
    await waitFor(() => expect(mockRemove).toHaveBeenCalledWith(11))
  })

  it('test_categories_page_delete_declined_does_not_call_remove', () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<CategoriesSettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'categories.delete' }))
    expect(confirmSpy).toHaveBeenCalled()
    expect(confirmSpy.mock.calls[0][0]).toContain('"count":"7"')
    expect(mockRemove).not.toHaveBeenCalled()
  })

  it('test_categories_page_backfill_preview_then_apply', async () => {
    render(<CategoriesSettingsPage />)
    expect(screen.queryByRole('button', { name: 'categories.backfillApply' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'categories.backfillPreview' }))
    await waitFor(() => expect(mockBackfill).toHaveBeenCalledWith(true))
    expect(await screen.findByText('categories.backfillMatched:{"count":"4"}')).toBeInTheDocument()

    mockBackfill.mockResolvedValue({ dry_run: false, matched: 4, applied: 4 })
    fireEvent.click(screen.getByRole('button', { name: 'categories.backfillApply' }))
    await waitFor(() => expect(mockBackfill).toHaveBeenCalledWith(false))
  })

  it('test_categories_page_backfill_zero_matches_hides_apply', async () => {
    mockBackfill.mockResolvedValue({ dry_run: true, matched: 0, applied: 0 })
    render(<CategoriesSettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'categories.backfillPreview' }))
    await screen.findByText('categories.backfillMatched:{"count":"0"}')
    expect(screen.queryByRole('button', { name: 'categories.backfillApply' })).toBeNull()
  })
})

describe('settingsRegistry categories entry', () => {
  it('test_settings_registry_categories_visible_to_admin_only', () => {
    expect(getVisibleCategories('member').some((c) => c.slug === 'categories')).toBe(false)
    expect(getVisibleCategories('admin').some((c) => c.slug === 'categories')).toBe(true)
  })
})
