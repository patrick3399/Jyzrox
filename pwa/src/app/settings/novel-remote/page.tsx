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
import { PageHeader } from '@/components/layout/PageHeader'
import { api } from '@/lib/api'
import type { NovelHostKey } from '@/lib/api/novels'
import { AlertDialog } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'

const BTN = 'text-xs bg-vault-accent/20 text-vault-accent hover:bg-vault-accent/30'

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
  const [recloneOpen, setRecloneOpen] = useState(false)

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
        setRecloneOpen(false)
        toast.success(t('novelRemote.saved'))
        await mutate()
      } else if (res.needsReclone) {
        setReclone({ reason: res.needsReclone.reason, unpushed: res.needsReclone.unpushed })
        setRecloneOpen(true)
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
      <PageHeader title={t('settingsCategory.novelRemote')} />

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
                  <Button variant="ghost" size="sm" className={BTN} onClick={handleCopy}>
                    <Copy size={14} />
                    {t('novelRemote.copy')}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className={BTN}
                  onClick={() => handleGenerate(hasKey)}
                  disabled={busy}
                >
                  {hasKey ? t('novelRemote.regenerateKey') : t('novelRemote.generateKey')}
                </Button>
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
              <Button
                variant="ghost"
                size="sm"
                className={BTN}
                onClick={() => handleSave(false)}
                disabled={actionsDisabled}
              >
                {t('novelRemote.save')}
              </Button>
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
                <Button
                  variant="ghost"
                  size="sm"
                  className={BTN}
                  onClick={handleScan}
                  disabled={!url || busy}
                >
                  {t('novelRemote.scanHost')}
                </Button>
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
                      <Button
                        variant="ghost"
                        size="sm"
                        className={BTN}
                        onClick={() => handleTrust(k.fingerprint)}
                        disabled={busy}
                      >
                        {t('novelRemote.trustHost')}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              className={BTN}
              onClick={handleTest}
              disabled={actionsDisabled}
            >
              {t('novelRemote.test')}
            </Button>
          </div>

          <AlertDialog
            open={recloneOpen}
            onOpenChange={(o) => {
              if (!o) setRecloneOpen(false)
            }}
            title={t('novelRemote.recloneTitle')}
            description={t('novelRemote.recloneBody', {
              reason: reclone?.reason ?? '',
              unpushed: String(reclone?.unpushed ?? 0),
            })}
            confirmLabel={t('novelRemote.recloneConfirm')}
            cancelLabel={t('novelRemote.cancel')}
            onConfirm={() => handleSave(true)}
            destructive
            busy={busy}
          />
        </>
      )}
    </div>
  )
}
