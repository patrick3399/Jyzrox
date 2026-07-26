import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ work: '%E4%BD%9C%E5%93%81A' }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/components/BackButton', () => ({ BackButton: () => null }))
vi.mock('@/components/LazyDialogs', () => ({ LazyNovelCreateDialog: () => null }))
vi.mock('@/components/novels/WorkCategorySection', () => ({ WorkCategorySection: () => null }))

const h = vi.hoisted(() => ({
  role: 'member' as string,
  chapters: [
    { path: '作品A/第01章.md', name: '第01章', chars: 1234, summary: '張三離開了城市', mtime: 0 },
    { path: '作品A/第02章.md', name: '第02章', chars: 20, summary: null, mtime: 0 },
  ],
  status: vi.fn(async () => ({ head: 'headsha', ahead: 0, behind: 0, clean: true, locked: false })),
  putSummary: vi.fn(async () => ({ head: 'newhead', pushed: true })),
  mutate: vi.fn(),
}))

vi.mock('swr', () => ({
  default: () => ({
    data: { chapters: h.chapters, categories: { extra: 0, draft: 0, reference: 0, scrap: 0 } },
    isLoading: false,
  }),
  mutate: (...args: unknown[]) => h.mutate(...args),
}))
vi.mock('@/hooks/useProfile', () => ({ useProfile: () => ({ data: { role: h.role } }) }))
vi.mock('@/lib/api', () => ({
  api: {
    novels: {
      listChapters: vi.fn(),
      status: () => h.status(),
      putSummary: (...args: unknown[]) => h.putSummary(...(args as [])),
    },
  },
}))

import NovelWorkPage from '@/app/novels/[work]/page'

describe('chapter summaries on the work page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.role = 'member'
  })

  it('shows the summary and a labelled character count per chapter', () => {
    render(<NovelWorkPage />)
    expect(screen.getByText('張三離開了城市')).toBeInTheDocument()
    // Real character count, rendered with a unit — not a bare byte size.
    expect(screen.getByText('novels.charCount 1,234')).toBeInTheDocument()
  })

  it('hides the summary editor from users without write access', () => {
    h.role = 'viewer'
    render(<NovelWorkPage />)
    expect(screen.queryByLabelText('novels.editSummary')).not.toBeInTheDocument()
  })

  it('saves an edited summary against a freshly read HEAD and refreshes the list', async () => {
    render(<NovelWorkPage />)
    await userEvent.click(screen.getAllByLabelText('novels.editSummary')[0])
    const box = screen.getByRole('textbox')
    expect(box).toHaveValue('張三離開了城市')
    await userEvent.clear(box)
    await userEvent.type(box, '張三回來了')
    await userEvent.click(screen.getByRole('button', { name: 'novels.save' }))
    await waitFor(() => expect(h.putSummary).toHaveBeenCalled())
    expect(h.status).toHaveBeenCalled()
    expect(h.putSummary).toHaveBeenCalledWith('作品A/第01章.md', '張三回來了', 'headsha')
    expect(h.mutate).toHaveBeenCalledWith(['novel-chapters', '作品A'])
  })

  it('closes the editor without writing when cancelled', async () => {
    render(<NovelWorkPage />)
    await userEvent.click(screen.getAllByLabelText('novels.editSummary')[1])
    await userEvent.click(screen.getByRole('button', { name: 'novels.cancel' }))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(h.putSummary).not.toHaveBeenCalled()
  })
})
