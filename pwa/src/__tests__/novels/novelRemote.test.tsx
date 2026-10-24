/**
 * Settings > Novel Sync Source (admin) — Vitest suite
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const m = vi.hoisted(() => ({
  guard: vi.fn(),
  get: vi.fn(),
  gen: vi.fn(),
  hostKeys: vi.fn(),
  trust: vi.fn(),
  test: vi.fn(),
  save: vi.fn(),
  mutate: vi.fn(),
  features: vi.fn(),
  swrKey: vi.fn(),
  setFeature: vi.fn(),
  swr: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/hooks/useAdminGuard', () => ({ useAdminGuard: () => m.guard() }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: { getFeatures: m.features },
    novels: {
      remoteGet: m.get,
      remoteGenerateKey: m.gen,
      remoteHostKeys: m.hostKeys,
      remoteTrust: m.trust,
      remoteTest: m.test,
      remoteSave: m.save,
    },
  },
}))
vi.mock('@/lib/featureSettings', () => ({ setFeatureAndSyncCache: m.setFeature }))
vi.mock('swr', () => ({
  default: (key: unknown) => {
    m.swrKey(key)
    return m.swr()
  },
}))
vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: m.toastSuccess, error: m.toastError } }))
vi.mock('@/components/BackButton', () => ({ BackButton: () => null }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

import NovelRemotePage from '@/app/settings/novel-remote/page'

const URL_ = 'u@h:/Novel.git'
const withKey = {
  url: URL_,
  repo_exists: true,
  has_key: true,
  public_key: 'ssh-ed25519 AAAA jyzrox-novel',
  key_fingerprint: 'SHA256:me',
  host_trusted: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  m.guard.mockReturnValue(true)
  m.features.mockResolvedValue({ novel_enabled: true })
  m.setFeature.mockResolvedValue(undefined)
  m.swr.mockReturnValue({ data: withKey, mutate: m.mutate, isLoading: false })
  m.hostKeys.mockResolvedValue({
    host: 'h',
    port: null,
    keys: [{ type: 'ed25519', fingerprint: 'SHA256:abc' }],
  })
  m.trust.mockResolvedValue({ ok: true })
  m.gen.mockResolvedValue({ public_key: 'ssh-ed25519 NEW', key_fingerprint: 'SHA256:new' })
  m.save.mockResolvedValue({ ok: true, mode: 'set_url' })
  m.test.mockResolvedValue({ ok: true, empty: false, error: '' })
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function renderReady() {
  render(<NovelRemotePage />)
  await screen.findByText('novelRemote.publicKey')
}

describe('NovelRemotePage', () => {
  it('test_novel_remote_with_key_shows_public_key_and_copy', async () => {
    await renderReady()
    expect(screen.getByText('ssh-ed25519 AAAA jyzrox-novel')).toBeInTheDocument()
    expect(screen.getByText('novelRemote.copy')).toBeInTheDocument()
    expect(screen.queryByText('novelRemote.noKey')).toBeNull()
  })

  it('test_novel_remote_without_key_disables_test_and_save', async () => {
    m.swr.mockReturnValue({
      data: { ...withKey, has_key: false, public_key: null },
      mutate: m.mutate,
      isLoading: false,
    })
    await renderReady()
    expect(screen.getByText('novelRemote.noKey')).toBeInTheDocument()
    expect(screen.getByText('novelRemote.test').closest('button')).toBeDisabled()
    expect(screen.getByText('novelRemote.save').closest('button')).toBeDisabled()
  })

  it('test_novel_remote_scan_lists_fingerprint_and_trust_sends_it', async () => {
    await renderReady()
    fireEvent.click(screen.getByText('novelRemote.scanHost'))
    await screen.findByText(/SHA256:abc/)
    expect(m.hostKeys).toHaveBeenCalledWith(URL_)
    fireEvent.click(screen.getByText('novelRemote.trustHost'))
    await waitFor(() => expect(m.trust).toHaveBeenCalledWith(URL_, 'SHA256:abc'))
  })

  it('test_novel_remote_save_set_url_toasts_without_confirm_dialog', async () => {
    await renderReady()
    fireEvent.click(screen.getByText('novelRemote.save'))
    await waitFor(() => expect(m.toastSuccess).toHaveBeenCalledWith('novelRemote.saved'))
    expect(m.save).toHaveBeenCalledWith(URL_)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('test_novel_remote_unrelated_409_opens_dialog_cancel_noop_confirm_resaves', async () => {
    m.save.mockResolvedValueOnce({
      ok: false,
      status: 409,
      message: 'unrelated',
      needsReclone: { reason: 'unrelated', unpushed: 3, dirty: false },
    })
    await renderReady()
    fireEvent.click(screen.getByText('novelRemote.save'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('"unpushed":"3"')

    fireEvent.click(screen.getByText('novelRemote.cancel'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(m.save).toHaveBeenCalledTimes(1)

    m.save.mockResolvedValueOnce({
      ok: false,
      status: 409,
      message: 'unrelated',
      needsReclone: { reason: 'unrelated', unpushed: 3, dirty: false },
    })
    fireEvent.click(screen.getByText('novelRemote.save'))
    await screen.findByRole('dialog')
    m.save.mockResolvedValueOnce({ ok: true, mode: 'recloned' })
    fireEvent.click(screen.getByText('novelRemote.recloneConfirm'))
    await waitFor(() => expect(m.save).toHaveBeenLastCalledWith(URL_, true))
  })

  it('test_novel_remote_regenerate_requires_window_confirm', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await renderReady()
    fireEvent.click(screen.getByText('novelRemote.regenerateKey'))
    expect(m.gen).not.toHaveBeenCalled()
    confirmSpy.mockReturnValue(true)
    fireEvent.click(screen.getByText('novelRemote.regenerateKey'))
    await waitFor(() => expect(m.gen).toHaveBeenCalledWith(true))
  })

  it('test_novel_remote_non_admin_renders_nothing', () => {
    m.guard.mockReturnValue(false)
    const { container } = render(<NovelRemotePage />)
    expect(container.innerHTML).toBe('')
  })

  it('test_novel_remote_module_off_hides_key_and_source_sections', async () => {
    m.features.mockResolvedValue({ novel_enabled: false })
    render(<NovelRemotePage />)
    await screen.findByText('settings.novelModule')
    expect(screen.queryByText('novelRemote.publicKey')).toBeNull()
    expect(screen.queryByLabelText('novelRemote.url')).toBeNull()
    expect(screen.queryByText('novelRemote.save')).toBeNull()
  })

  it('test_novel_remote_toggle_on_saves_flag_and_reveals_sections', async () => {
    m.features.mockResolvedValue({ novel_enabled: false })
    render(<NovelRemotePage />)
    await screen.findByText('settings.novelModule')
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(m.setFeature).toHaveBeenCalledWith('novel_enabled', true))
    await screen.findByText('novelRemote.publicKey')
  })

  it('test_novel_remote_host_trust_is_queried_for_the_typed_url', async () => {
    // Regression: the badge used to depend on the saved remote only, so it read
    // "not trusted" for an already-trusted host before the first save.
    await renderReady()
    fireEvent.change(screen.getByLabelText('novelRemote.url'), {
      target: { value: 'u@new.example:/Novel.git' },
    })
    await waitFor(() =>
      expect(m.swrKey).toHaveBeenLastCalledWith(['novel-remote', 'u@new.example:/Novel.git']),
    )
  })

  it('test_novel_remote_save_sits_with_the_url_and_test_is_last', async () => {
    await renderReady()
    const input = screen.getByLabelText('novelRemote.url')
    const save = screen.getByText('novelRemote.save')
    const test = screen.getByText('novelRemote.test')
    const after = (a: Node, b: Node) =>
      a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING
    // Save follows the URL field and precedes the host block and the test button.
    expect(after(input, save)).toBeTruthy()
    expect(after(save, screen.getByText('novelRemote.scanHost'))).toBeTruthy()
    expect(after(save, test)).toBeTruthy()
    expect(after(screen.getByText('novelRemote.scanHost'), test)).toBeTruthy()
  })
})
