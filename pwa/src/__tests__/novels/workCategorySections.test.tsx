import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorkCategorySection } from '@/components/novels/WorkCategorySection'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))
const listWorkFiles = vi.fn().mockResolvedValue({
  files: [{ path: '作品A/Old/01.md', name: '01', chars: 10, mtime: 0, category: 'scrap' }],
})
vi.mock('@/lib/api', () => ({ api: { novels: { get listWorkFiles() { return listWorkFiles } } } }))

describe('WorkCategorySection', () => {
  it('renders nothing when the category is empty', () => {
    const { container } = render(<WorkCategorySection work="作品A" category="scrap" count={0} />)
    expect(container.firstChild).toBeNull()
    expect(listWorkFiles).not.toHaveBeenCalled()
  })

  it('lazy-loads files only after the section is expanded', async () => {
    render(<WorkCategorySection work="作品A" category="scrap" count={1} />)
    expect(listWorkFiles).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.getByText('01')).toBeInTheDocument())
    expect(listWorkFiles).toHaveBeenCalledWith('作品A', 'scrap')
  })
})
