'use client'

import { useState, useCallback } from 'react'
import { ChevronUp, ChevronDown, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { Button } from '@/components/ui/button'
import { inputClass, StatusBadge } from '@/components/credentials/shared'

// ── SauceNAO API key section ──────────────────────────────────────────────

export function SauceNaoSection({
  configured,
  isOpen,
  onToggle,
  onSaved,
}: {
  configured: boolean
  isOpen: boolean
  onToggle: () => void
  onSaved: () => void
}) {
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSave = useCallback(async () => {
    if (!apiKey.trim()) return
    setSaving(true)
    try {
      await api.settings.setSaucenaoApiKey(apiKey.trim())
      toast.success(t('saucenao.apiKeySaved'))
      setApiKey('')
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setSaving(false)
    }
  }, [apiKey, onSaved])

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between">
        <button
          onClick={onToggle}
          className="flex-1 flex items-center justify-between px-5 py-4 text-left hover:bg-vault-card-hover transition-colors"
        >
          <span className="font-medium text-vault-text text-sm">SauceNAO</span>
          {isOpen ? (
            <ChevronUp size={16} className="text-vault-text-muted" />
          ) : (
            <ChevronDown size={16} className="text-vault-text-muted" />
          )}
        </button>
        <div className="pr-5 shrink-0">
          <StatusBadge configured={configured} />
        </div>
      </div>

      {isOpen && (
        <div className="px-5 pb-5 border-t border-vault-border">
          <div className="mt-4 space-y-3">
            <div>
              <label className="block text-sm text-vault-text-secondary mb-1">
                {t('saucenao.apiKey')}
              </label>
              <input
                type="password"
                className={inputClass}
                placeholder={t('saucenao.apiKeyPlaceholder')}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSave()}
              />
              <p className="text-xs text-vault-text-muted mt-1">{t('saucenao.apiKeyHint')}</p>
            </div>
            <Button
              variant="primary"
              size="md"
              onClick={handleSave}
              disabled={saving || !apiKey.trim()}
            >
              {saving ? t('credentials.saving') : t('saucenao.saveApiKey')}
            </Button>
          </div>

          {configured && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-4 border border-red-500/30 bg-red-600/20 text-red-400 hover:bg-red-600/30"
              onClick={async () => {
                try {
                  await api.settings.deleteCredential('saucenao')
                  toast.success(t('saucenao.apiKeyCleared'))
                  onSaved()
                } catch {
                  toast.error(t('credentials.clearFailed'))
                }
              }}
            >
              <Trash2 size={13} />
              {t('saucenao.clearApiKey')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
