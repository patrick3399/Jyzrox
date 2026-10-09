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
import { parseQuery } from '@/lib/queryParser'

const data = {
  categories: [
    { id: 1, name: 'Cosplay', color: 'red', sort_order: 8, is_builtin: true, gallery_count: 3 },
    { id: 11, name: 'Novel', color: 'teal', sort_order: 11, is_builtin: false, gallery_count: 7 },
  ],
  palette: ['red', 'teal', 'gray'],
  uncategorized_count: 12,
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

  it('test_categories_page_builtin_and_custom_names_link_to_library_category_filter', () => {
    render(<CategoriesSettingsPage />)
    expect(screen.getByRole('link', { name: /Cosplay/ })).toHaveAttribute(
      'href',
      '/library?q=category%3ACosplay',
    )
    expect(screen.getByRole('link', { name: /Novel/ })).toHaveAttribute(
      'href',
      '/library?q=category%3ANovel',
    )
  })

  it('test_categories_page_library_link_url_encodes_special_characters_in_name', () => {
    mockRegistry.mockReturnValue({
      data: {
        ...data,
        categories: [
          { id: 12, name: 'Sci-Fi & Co', color: 'teal', sort_order: 12, is_builtin: false, gallery_count: 1 },
        ],
      },
      mutate: mockMutate,
      isLoading: false,
    })
    render(<CategoriesSettingsPage />)
    expect(screen.getByRole('link', { name: /Sci-Fi & Co/ })).toHaveAttribute(
      'href',
      '/library?q=category%3A%22Sci-Fi%20%26%20Co%22',
    )
  })

  it('test_categories_page_library_links_round_trip_through_the_library_query_parser', () => {
    mockRegistry.mockReturnValue({
      data: {
        ...data,
        categories: [
          { id: 1, name: 'Artist CG', color: 'yellow', sort_order: 3, is_builtin: true, gallery_count: 2 },
        ],
      },
      mutate: mockMutate,
      isLoading: false,
    })
    render(<CategoriesSettingsPage />)
    const href = screen.getByRole('link', { name: /Artist CG/ }).getAttribute('href') ?? ''
    const q = new URL(href, 'http://x').searchParams.get('q') ?? ''
    expect(parseQuery(q).category).toBe('Artist CG')
    const uncategorized = screen.getByRole('link', { name: /library\.categoryUncategorized/ })
    const uq = new URL(uncategorized.getAttribute('href') ?? '', 'http://x').searchParams.get('q') ?? ''
    expect(parseQuery(uq).category).toBe('__uncategorized__')
  })

  it('test_categories_page_uncategorized_section_shows_count_and_links_to_uncategorized_filter', () => {
    render(<CategoriesSettingsPage />)
    const link = screen.getByRole('link', { name: /library\.categoryUncategorized/ })
    expect(link).toHaveAttribute('href', '/library?q=category%3A__uncategorized__')
    expect(screen.getByText('categories.galleryCount:{"count":"12"}')).toBeInTheDocument()
  })

  it('test_categories_page_uncategorized_section_still_renders_when_count_is_zero', () => {
    mockRegistry.mockReturnValue({
      data: { ...data, uncategorized_count: 0 },
      mutate: mockMutate,
      isLoading: false,
    })
    render(<CategoriesSettingsPage />)
    expect(screen.getByRole('link', { name: /library\.categoryUncategorized/ })).toBeInTheDocument()
    expect(screen.getByText('categories.galleryCount:{"count":"0"}')).toBeInTheDocument()
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
