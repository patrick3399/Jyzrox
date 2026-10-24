'use client'

import { useEffect, useState } from 'react'
import useSWR from 'swr'
import { toast } from 'sonner'
import { Copy } from 'lucide-react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { ToggleRow } from '@/components/settings/SettingsShared'
import { setFeatureAndSyncCache } from '@/lib/featureSettings'
import { t } from '@/lib/i18n'
import { api } from '@/lib/api'
import type { NovelHostKey } from '@/lib/api/novels'

const BTN =
  'px-3 py-1.5 rounded text-xs font-medium bg-vault-accent/20 text-vault-accent hover:bg-vault-accent/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

export default function NovelRemoteSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  // The module switch lives on this page; the key / remote sections only
  // render once it is on. null = still loading the flag.
  const [enabled, setEnabled] = useState<boolean | null>(null)

  useEffect(() => {
    if (!authorized) return
    api.settings
      .getFeatures()
      .then((data) =>
        setEnabled(Boolean((data as unknown as Record<string, boolean>).novel_enabled)),
      )
      .catch(() => setEnabled(false))
  }, [authorized])

  const handleToggle = async (next: boolean) => {
    try {
      await setFeatureAndSyncCache('novel_enabled', next)
      setEnabled(next)
      toast.success(t('common.saved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    }
  }

  // null = untouched, fall back to the saved URL (avoids a seeding effect).
  const [urlEdit, setUrlEdit] = useState<string | null>(null)
  const [hostKeys, setHostKeys] = useState<NovelHostKey[]>([])
  const [busy, setBusy] = useState(false)
  const [reclone, setReclone] = useState<{ reason: string; unpushed: number } | null>(null)

  // Debounced copy of the typed URL: host trust is judged on what is typed, not
  // only on the saved remote (there is none before the first save).
  const [probeUrl, setProbeUrl] = useState('')
  useEffect(() => {
    const id = setTimeout(() => setProbeUrl(urlEdit ?? ''), 400)
    return () => clearTimeout(id)
  }, [urlEdit])
  const { data: info, mutate } = useSWR(['novel-remote', probeUrl], ([, u]) =>
    api.novels.remoteGet(u || undefined),
  )

  const url = urlEdit ?? info?.url ?? ''

  const fail = (err: unknown) => {
    toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
  }

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    try {
      await fn()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(info?.public_key ?? '')
      toast.success(t('novelRemote.copied'))
    } catch (err) {
      fail(err)
    }
  }

  const handleGenerate = (regenerate: boolean) => {
    if (regenerate && !window.confirm(t('novelRemote.regenerateConfirm'))) return
    void run(async () => {
      await api.novels.remoteGenerateKey(regenerate)
      await mutate()
    })
  }

  const handleScan = () =>
    run(async () => {
      const res = await api.novels.remoteHostKeys(url)
      setHostKeys(res.keys)
    })

  const handleTrust = (fingerprint: string) =>
    run(async () => {
      await api.novels.remoteTrust(url, fingerprint)
      toast.success(t('novelRemote.hostTrusted'))
      setHostKeys([])
      await mutate()
    })

  const handleTest = () =>
    run(async () => {
      const res = await api.novels.remoteTest(url)
      if (!res.ok) toast.error(res.error || t('common.failedToLoad'))
      else if (res.empty) toast.success(t('novelRemote.testEmpty'))
      else toast.success(t('novelRemote.testOk'))
    })

  const handleSave = (confirmReclone: boolean) =>
    run(async () => {
      const res = confirmReclone
        ? await api.novels.remoteSave(url, true)
        : await api.novels.remoteSave(url)
      if (res.ok) {
        setReclone(null)
        toast.success(t('novelRemote.saved'))
        await mutate()
      } else if (res.needsReclone) {
        setReclone({ reason: res.needsReclone.reason, unpushed: res.needsReclone.unpushed })
      } else {
        toast.error(res.message)
      }
    })

  if (!authorized) return null

  const hasKey = info?.has_key ?? false
  const actionsDisabled = !hasKey || !url || busy

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">
        {t('settingsCategory.novelRemote')}
      </h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-4">
        <div className="px-5">
          <ToggleRow
            label={t('settings.novelModule')}
            description={t('settings.novelModuleDesc')}
            checked={enabled ?? false}
            onChange={handleToggle}
            disabled={enabled === null}
          />
        </div>
      </div>

      {enabled && (
        <>
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-4">
            <div className="px-5 py-4 space-y-3">
              <p className="text-sm text-vault-text">{t('novelRemote.publicKey')}</p>
              {hasKey && info?.public_key ? (
                <>
                  <pre className="text-xs text-vault-text bg-vault-bg border border-vault-border rounded p-3 whitespace-pre-wrap break-all">
                    {info.public_key}
                  </pre>
                  <p className="text-xs text-vault-text-muted">{t('novelRemote.publicKeyHelp')}</p>
                </>
              ) : (
                <p className="text-xs text-vault-text-muted">{t('novelRemote.noKey')}</p>
              )}
              <div className="flex gap-2">
                {hasKey && (
                  <button onClick={handleCopy} className={`${BTN} flex items-center gap-1.5`}>
                    <Copy size={14} />
                    {t('novelRemote.copy')}
                  </button>
                )}
                <button onClick={() => handleGenerate(hasKey)} disabled={busy} className={BTN}>
                  {hasKey ? t('novelRemote.regenerateKey') : t('novelRemote.generateKey')}
                </button>
              </div>
            </div>
          </div>

          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-4">
            <div className="px-5 py-4 space-y-3">
              <label className="text-sm text-vault-text block" htmlFor="novel-remote-url">
                {t('novelRemote.url')}
              </label>
              <input
                id="novel-remote-url"
                aria-label={t('novelRemote.url')}
                value={url}
                onChange={(e) => {
                  setUrlEdit(e.target.value)
                  setHostKeys([])
                }}
                className="w-full bg-vault-bg border border-vault-border rounded px-3 py-2 text-sm text-vault-text"
              />
              <p className="text-xs text-vault-text-muted">{t('novelRemote.urlHelp')}</p>
              <button onClick={() => handleSave(false)} disabled={actionsDisabled} className={BTN}>
                {t('novelRemote.save')}
              </button>
            </div>
          </div>

          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-4">
            <div className="px-5 py-4 space-y-3">
              <div className="flex items-center justify-between">
                <span
                  className={`text-xs font-medium ${info?.host_trusted ? 'text-green-400' : 'text-yellow-400'}`}
                >
                  {info?.host_trusted
                    ? t('novelRemote.hostTrusted')
                    : t('novelRemote.hostNotTrusted')}
                </span>
                <button onClick={handleScan} disabled={!url || busy} className={BTN}>
                  {t('novelRemote.scanHost')}
                </button>
              </div>
              {hostKeys.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs text-vault-text-muted">
                    {t('novelRemote.hostFingerprints')}
                  </p>
                  {hostKeys.map((k) => (
                    <div key={k.fingerprint} className="flex items-center justify-between gap-2">
                      <code className="text-xs text-vault-text break-all">
                        {k.type} {k.fingerprint}
                      </code>
                      <button
                        onClick={() => handleTrust(k.fingerprint)}
                        disabled={busy}
                        className={BTN}
                      >
                        {t('novelRemote.trustHost')}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex gap-2">
            <button onClick={handleTest} disabled={actionsDisabled} className={BTN}>
              {t('novelRemote.test')}
            </button>
          </div>

          {reclone && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
              <div
                role="dialog"
                aria-modal="true"
                className="bg-vault-card border border-vault-border rounded-xl p-5 max-w-md w-full space-y-4"
              >
                <h2 className="text-lg font-semibold text-vault-text">
                  {t('novelRemote.recloneTitle')}
                </h2>
                <p className="text-sm text-vault-text-muted">
                  {t('novelRemote.recloneBody', {
                    reason: reclone.reason,
                    unpushed: String(reclone.unpushed),
                  })}
                </p>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setReclone(null)} className={BTN}>
                    {t('novelRemote.cancel')}
                  </button>
                  <button
                    onClick={() => handleSave(true)}
                    disabled={busy}
                    className="px-3 py-1.5 rounded text-xs font-medium bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50"
                  >
                    {t('novelRemote.recloneConfirm')}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
