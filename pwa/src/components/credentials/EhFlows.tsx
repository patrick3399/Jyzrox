'use client'

import { useState } from 'react'
import { Eye, EyeOff, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { EhAccount } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { inputClass } from '@/components/credentials/shared'

// ── EhExtras: site toggle + account info ──────────────────────────────────

export function EhExtras({
  ehAccount,
  ehAccountLoading,
  onRefresh,
  useEx,
  useExLoading,
  onToggleEx,
}: {
  ehAccount: EhAccount | null
  ehAccountLoading: boolean
  onRefresh: () => void
  useEx: boolean
  useExLoading: boolean
  onToggleEx: () => void
}) {
  return (
    <>
      {/* Site toggle */}
      <div className="flex items-center justify-between mb-4 mt-4">
        <div>
          <p className="text-sm text-vault-text">{t('credentials.ehSite')}</p>
          <p className="text-xs text-vault-text-muted mt-0.5">{t('credentials.ehSiteDesc')}</p>
        </div>
        <div className="flex bg-vault-input border border-vault-border rounded overflow-hidden">
          <button
            onClick={() => useEx && onToggleEx()}
            disabled={useExLoading}
            className={`px-3 py-1.5 text-xs transition-colors ${!useEx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('credentials.ehSiteEh')}
          </button>
          <button
            onClick={() => !useEx && onToggleEx()}
            disabled={useExLoading}
            className={`px-3 py-1.5 text-xs transition-colors ${useEx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('credentials.ehSiteEx')}
          </button>
        </div>
      </div>

      {/* Refresh account button */}
      <div className="mb-3">
        <Button variant="secondary" size="md" onClick={onRefresh} disabled={ehAccountLoading}>
          <RefreshCw size={14} className="inline mr-1.5" />
          {ehAccountLoading ? t('settings.refreshing') : t('settings.refreshAccount')}
        </Button>
      </div>

      {/* Account info */}
      {ehAccount && (
        <div className="mt-2 bg-vault-input border border-vault-border rounded-lg p-3">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
            {t('settings.accountStatus')}
          </p>
          <div className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-vault-text-muted">{t('settings.valid')}</span>
              <span className={ehAccount.valid ? 'text-green-400' : 'text-red-400'}>
                {ehAccount.valid ? t('settings.yes') : t('settings.no')}
              </span>
            </div>
            {ehAccount.credits !== undefined && (
              <div className="flex justify-between text-sm">
                <span className="text-vault-text-muted">{t('settings.credits')}</span>
                <span className="text-vault-text-secondary">
                  {ehAccount.credits.toLocaleString()}
                </span>
              </div>
            )}
            {ehAccount.hath_perks !== undefined && (
              <div className="flex justify-between text-sm">
                <span className="text-vault-text-muted">{t('settings.hathPerks')}</span>
                <span className="text-vault-text-secondary">{ehAccount.hath_perks}</span>
              </div>
            )}
            {ehAccount.error && <p className="text-xs text-red-400 mt-1">{ehAccount.error}</p>}
          </div>
        </div>
      )}
    </>
  )
}

// ── EhFieldsFlow ──────────────────────────────────────────────────────────

export function EhFieldsFlow({
  onSaved,
  saveAs,
}: {
  onSaved: (account: EhAccount) => void
  saveAs?: string
}) {
  const [memberId, setMemberId] = useState('')
  const [passHash, setPassHash] = useState('')
  const [sk, setSk] = useState('')
  const [igneous, setIgneous] = useState('')
  const [saving, setSaving] = useState(false)
  const [showPassHash, setShowPassHash] = useState(false)

  const handleSave = async () => {
    if (!memberId.trim() || !passHash.trim()) return
    setSaving(true)
    try {
      const data: { ipb_member_id: string; ipb_pass_hash: string; sk?: string; igneous?: string } =
        { ipb_member_id: memberId.trim(), ipb_pass_hash: passHash.trim() }
      if (sk.trim()) data.sk = sk.trim()
      if (igneous.trim()) data.igneous = igneous.trim()
      const result = await api.settings.setEhCookies(data, saveAs)
      toast.success(t('settings.ehCookiesSaved'))
      onSaved(result.account)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.ehCookiesFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-vault-text-muted">{t('credentials.ehCookieOnlyHint')}</p>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">ipb_member_id</label>
        <input
          type="text"
          value={memberId}
          onChange={(e) => setMemberId(e.target.value)}
          placeholder={t('settings.enterIpbMemberId')}
          className={inputClass}
        />
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">ipb_pass_hash</label>
        <div className="relative">
          <input
            type={showPassHash ? 'text' : 'password'}
            value={passHash}
            onChange={(e) => setPassHash(e.target.value)}
            placeholder={t('settings.enterIpbPassHash')}
            className={`${inputClass} pr-10`}
          />
          <button
            type="button"
            onClick={() => setShowPassHash((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-vault-text-muted hover:text-vault-text transition-colors px-1"
          >
            {showPassHash ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('settings.ehIgneousLabel')}
        </label>
        <input
          type="text"
          value={igneous}
          onChange={(e) => setIgneous(e.target.value)}
          placeholder={t('settings.enterIgneous')}
          className={inputClass}
        />
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('settings.ehSkLabel')}
        </label>
        <input
          type="text"
          value={sk}
          onChange={(e) => setSk(e.target.value)}
          placeholder={t('settings.enterSk')}
          className={inputClass}
        />
      </div>
      <Button
        variant="primary"
        size="md"
        onClick={handleSave}
        disabled={saving || !memberId.trim() || !passHash.trim()}
      >
        {saving ? t('settings.saving') : t('settings.saveCookies')}
      </Button>
    </div>
  )
}
