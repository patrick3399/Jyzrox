'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  BTN,
  INPUT,
  LABEL,
  toProfile,
  BrowserOptions,
} from '@/components/settings/egress-personas/shared'

export function CreateForm({ onCreated }: { onCreated: () => Promise<unknown> }) {
  const [name, setName] = useState('')
  const [proxyUrl, setProxyUrl] = useState('')
  const [browser, setBrowser] = useState('')
  const [userAgent, setUserAgent] = useState('')
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      // browser_profile and user_agent are mutually exclusive (ADR 0022).
      await api.adminPersonas.create({
        name: name.trim(),
        proxy_url: proxyUrl.trim() || null,
        browser_profile: toProfile(browser),
        user_agent: browser ? null : userAgent.trim() || null,
      })
      setName('')
      setProxyUrl('')
      setBrowser('')
      setUserAgent('')
      toast.success(t('common.saved'))
      await onCreated()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-vault-card border border-vault-border rounded-xl p-4 mb-4 space-y-3"
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor="persona-new-name" className={LABEL}>
            {t('personas.name')}
          </label>
          <input
            id="persona-new-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={INPUT}
          />
        </div>
        <div>
          <label htmlFor="persona-new-proxy" className={LABEL}>
            {t('personas.proxyUrl')}
          </label>
          <input
            id="persona-new-proxy"
            type="text"
            value={proxyUrl}
            onChange={(e) => setProxyUrl(e.target.value)}
            placeholder={t('personas.proxyDirect')}
            className={INPUT}
          />
        </div>
        <div>
          <label htmlFor="persona-new-browser" className={LABEL}>
            {t('personas.browserProfile')}
          </label>
          <select
            id="persona-new-browser"
            value={browser}
            onChange={(e) => {
              setBrowser(e.target.value)
              if (e.target.value) setUserAgent('')
            }}
            className={INPUT}
          >
            <BrowserOptions />
          </select>
        </div>
        <div>
          <label htmlFor="persona-new-ua" className={LABEL}>
            {t('personas.userAgent')}
          </label>
          <input
            id="persona-new-ua"
            type="text"
            value={userAgent}
            disabled={browser !== ''}
            onChange={(e) => setUserAgent(e.target.value)}
            className={INPUT}
          />
        </div>
      </div>
      <p className="text-xs text-vault-text-muted">{t('personas.identityHint')}</p>
      <Button
        variant="ghost"
        size="sm"
        className={BTN}
        type="submit"
        disabled={busy || !name.trim()}
      >
        {t('personas.create')}
      </Button>
    </form>
  )
}
