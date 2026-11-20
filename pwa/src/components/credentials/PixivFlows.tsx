'use client'

import { useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { Button } from '@/components/ui/button'
import { inputClass } from '@/components/credentials/shared'

// ── PixivOAuthFlow ────────────────────────────────────────────────────────

export function PixivOAuthFlow({
  onSaved,
  saveAs,
}: {
  onSaved: (username: string) => void
  saveAs?: string
}) {
  const [_oauthUrl, setOauthUrl] = useState('')
  const [codeVerifier, setCodeVerifier] = useState('')
  const [callbackUrl, setCallbackUrl] = useState('')
  const [saving, setSaving] = useState(false)

  const handleGetUrl = async () => {
    try {
      const res = await api.settings.getPixivOAuthUrl()
      setOauthUrl(res.url)
      setCodeVerifier(res.code_verifier)
      window.open(res.url, '_blank')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const handleExchange = async () => {
    if (!callbackUrl.trim() || !codeVerifier) return
    setSaving(true)
    try {
      const res = await api.settings.pixivOAuthCallback(callbackUrl.trim(), codeVerifier, saveAs)
      toast.success(`${t('settings.pixivSaved')}: ${res.username}`)
      onSaved(res.username)
      setCallbackUrl('')
      setOauthUrl('')
      setCodeVerifier('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 mt-2">
      <div className="bg-yellow-900/20 border border-yellow-700/30 rounded-lg p-3 text-xs text-yellow-300/90 space-y-1.5">
        <p className="font-semibold">{t('settings.pixivOauthSteps')}</p>
        <p>{t('settings.pixivOauthStep1')}</p>
        <p>{t('settings.pixivOauthStep2')}</p>
        <p>{t('settings.pixivOauthStep3')}</p>
        <p className="text-yellow-400/70">
          {t('settings.pixivOauthHint')}{' '}
          <code className="bg-black/30 px-1 rounded">https://app-api.pixiv.net/...?code=xxx</code>
        </p>
        <p className="text-yellow-400/70">{t('settings.pixivOauthHint2')}</p>
      </div>
      <Button variant="secondary" size="md" className="w-full gap-2" onClick={handleGetUrl}>
        <ExternalLink size={14} />
        {t('credentials.oauthGetUrl')}
      </Button>
      {codeVerifier && (
        <div>
          <p className="text-xs text-vault-text-muted mb-1">{t('settings.pixivOauthStep4')}</p>
          <input
            type="text"
            value={callbackUrl}
            onChange={(e) => setCallbackUrl(e.target.value)}
            placeholder={t('credentials.oauthPasteCallback')}
            className={inputClass}
          />
          <Button
            variant="primary"
            size="md"
            className="mt-3"
            onClick={handleExchange}
            disabled={saving || !callbackUrl.trim()}
          >
            {saving ? t('settings.saving') : t('credentials.oauthExchange')}
          </Button>
        </div>
      )}
    </div>
  )
}

// ── PixivTokenFlow ────────────────────────────────────────────────────────

export function PixivTokenFlow({
  onSaved,
  saveAs,
}: {
  onSaved: (username: string) => void
  saveAs?: string
}) {
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!token.trim()) return
    setSaving(true)
    try {
      const result = await api.settings.setPixivToken(token.trim(), saveAs)
      toast.success(`${t('settings.pixivSaved')}: ${result.username}`)
      onSaved(result.username)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 mt-2">
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('settings.pixivRefreshToken')}
        </label>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={t('settings.enterPixivRefreshToken')}
          className={inputClass}
        />
        <p className="text-xs text-vault-text-muted mt-1">{t('settings.pixivHint')}</p>
      </div>
      <Button variant="primary" size="md" onClick={handleSave} disabled={saving || !token.trim()}>
        {saving ? t('settings.saving') : t('settings.saveToken')}
      </Button>
    </div>
  )
}

// ── PixivCookieFlow ───────────────────────────────────────────────────────

export function PixivCookieFlow({
  onSaved,
  saveAs,
}: {
  onSaved: (username: string) => void
  saveAs?: string
}) {
  const [cookie, setCookie] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!cookie.trim()) return
    setSaving(true)
    try {
      const result = await api.settings.setPixivCookie(cookie.trim(), saveAs)
      toast.success(`${t('settings.pixivSaved')}: ${result.username}`)
      onSaved(result.username)
      setCookie('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 mt-2">
      <div className="bg-blue-900/20 border border-blue-700/30 rounded-lg p-3 text-xs text-blue-300/90 space-y-1.5">
        <p className="font-semibold">{t('settings.pixivCookieTitle')}</p>
        <p>{t('settings.pixivCookieDesc')}</p>
        <ul className="list-disc list-inside mt-1 ml-1">
          <li>{t('settings.pixivCookieStep1')}</li>
          <li>{t('settings.pixivCookieStep2')}</li>
          <li>
            {t('settings.pixivCookieStep3')}{' '}
            <code className="bg-black/30 px-1 rounded">PHPSESSID</code>
          </li>
          <li>{t('settings.pixivCookieStep4')}</li>
        </ul>
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('credentials.sessionCookie')} (PHPSESSID)
        </label>
        <input
          type="password"
          value={cookie}
          onChange={(e) => setCookie(e.target.value)}
          placeholder={t('settings.pixivTokenExample')}
          className={inputClass}
        />
      </div>
      <Button variant="primary" size="md" onClick={handleSave} disabled={saving || !cookie.trim()}>
        {saving ? t('settings.saving') : t('credentials.oauthExchange')}
      </Button>
    </div>
  )
}
