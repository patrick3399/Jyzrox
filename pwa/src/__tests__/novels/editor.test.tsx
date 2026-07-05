import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const h = vi.hoisted(() => {
  const mockFile = {
    path: '作品A/第01章.md',
    content: 'original body',
    base_sha: 'sha-100',
    acts: [],
    backlinks: [],
  }
  return { mockFile, writeFile: vi.fn() }
})

vi.mock('swr', () => ({
  default: () => ({ data: h.mockFile, isLoading: false }),
}))

vi.mock('@/lib/api', () => ({
  api: {
    novels: {
      readFile: vi.fn().mockResolvedValue(h.mockFile),
      writeFile: h.writeFile,
    },
  },
}))

import { Editor } from '@/components/novels/Editor'

describe('Editor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
  })

  it('saves with the loaded base_sha', async () => {
    h.writeFile.mockResolvedValue({ ok: true, head: 'sha-200', pushed: true })
    render(<Editor path="作品A/第01章.md" onSaved={vi.fn()} onCancel={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('novels.edit'), { target: { value: 'new body' } })
    fireEvent.click(screen.getByRole('button', { name: 'novels.save' }))
    await waitFor(() =>
      expect(h.writeFile).toHaveBeenCalledWith(
        expect.objectContaining({ path: '作品A/第01章.md', content: 'new body', base_sha: 'sha-100' }),
      ),
    )
  })

  it('surfaces the stale-conflict hint with the server version on 409', async () => {
    h.writeFile.mockResolvedValue({
      ok: false,
      status: 409,
      conflict: { current: 'server body', current_sha: 'sha-999' },
    })
    render(<Editor path="作品A/第01章.md" onSaved={vi.fn()} onCancel={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'novels.save' }))
    await screen.findByText('novels.staleConflict')
    expect(screen.getByText('server body')).toBeInTheDocument()
  })

  it('detects a saved draft for the same base_sha and offers restore', async () => {
    window.localStorage.setItem('novel:draft:作品A/第01章.md:sha-100', 'draft body')
    render(<Editor path="作品A/第01章.md" onSaved={vi.fn()} onCancel={vi.fn()} />)
    await screen.findByText('novels.draftRestored')
    fireEvent.click(screen.getByRole('button', { name: 'novels.restoreDraft' }))
    expect((screen.getByLabelText('novels.edit') as HTMLTextAreaElement).value).toBe('draft body')
  })
})
