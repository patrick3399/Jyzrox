import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

const h = vi.hoisted(() => ({ createFile: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: { novels: { createFile: h.createFile } } }))

import { NovelCreateDialog } from '@/components/novels/NovelCreateDialog'

describe('NovelCreateDialog', () => {
  beforeEach(() => vi.clearAllMocks())

  it('creates a new work from work name + first chapter name', async () => {
    h.createFile.mockResolvedValue({ ok: true, head: 'sha', pushed: true })
    const onCreated = vi.fn()
    render(<NovelCreateDialog mode="work" onClose={vi.fn()} onCreated={onCreated} />)

    fireEvent.change(screen.getByLabelText('novels.workName'), { target: { value: '新作品' } })
    fireEvent.change(screen.getByLabelText('novels.firstChapterName'), {
      target: { value: '第一章' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'novels.create' }))

    await waitFor(() => expect(h.createFile).toHaveBeenCalledWith('新作品', '第一章', undefined))
    expect(onCreated).toHaveBeenCalledWith('新作品', '第一章', '新作品/第一章.md')
  })

  it('creates a chapter in an existing work', async () => {
    h.createFile.mockResolvedValue({ ok: true, head: 'sha', pushed: true })
    const onCreated = vi.fn()
    render(<NovelCreateDialog mode="chapter" work="作品A" onClose={vi.fn()} onCreated={onCreated} />)

    fireEvent.change(screen.getByLabelText('novels.chapterName'), { target: { value: '第二章' } })
    fireEvent.click(screen.getByRole('button', { name: 'novels.create' }))

    await waitFor(() => expect(h.createFile).toHaveBeenCalledWith('作品A', '第二章', undefined))
    expect(onCreated).toHaveBeenCalledWith('作品A', '第二章', '作品A/第二章.md')
  })

  it('rejects an empty name without calling the API', () => {
    render(<NovelCreateDialog mode="chapter" work="作品A" onClose={vi.fn()} onCreated={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'novels.create' }))
    expect(screen.getByText('novels.nameRequired')).toBeInTheDocument()
    expect(h.createFile).not.toHaveBeenCalled()
  })

  it('rejects a name containing a slash', () => {
    render(<NovelCreateDialog mode="chapter" work="作品A" onClose={vi.fn()} onCreated={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('novels.chapterName'), {
      target: { value: 'a/b' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'novels.create' }))
    expect(screen.getByText('novels.nameInvalid')).toBeInTheDocument()
    expect(h.createFile).not.toHaveBeenCalled()
  })

  it('surfaces a file-exists conflict from the server', async () => {
    h.createFile.mockResolvedValue({ ok: false, status: 409, message: 'file exists' })
    render(<NovelCreateDialog mode="chapter" work="作品A" onClose={vi.fn()} onCreated={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('novels.chapterName'), { target: { value: '第一章' } })
    fireEvent.click(screen.getByRole('button', { name: 'novels.create' }))
    await waitFor(() => expect(screen.getByText('novels.fileExists')).toBeInTheDocument())
  })

  it('creates the file inside the chosen category folder', async () => {
    h.createFile.mockResolvedValue({ ok: true, head: 'sha', pushed: true })
    const onCreated = vi.fn()
    render(<NovelCreateDialog mode="chapter" work="作品A" onClose={vi.fn()} onCreated={onCreated} />)

    fireEvent.change(screen.getByLabelText('novels.createCategory'), { target: { value: '草稿' } })
    fireEvent.change(screen.getByLabelText('novels.chapterName'), { target: { value: '03alt' } })
    fireEvent.click(screen.getByRole('button', { name: 'novels.create' }))

    await waitFor(() => expect(h.createFile).toHaveBeenCalledWith('作品A', '03alt', '草稿'))
    expect(onCreated).toHaveBeenCalledWith('作品A', '03alt', '作品A/草稿/03alt.md')
  })
})
