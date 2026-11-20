'use client'

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { PluginInfo, CredentialFlow, FieldDef } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { inputClass } from '@/components/credentials/shared'

// ── GenericFieldsFlow: renders any plugin's `fields` flow from its schema ──

export function GenericField({
  field,
  value,
  onChange,
}: {
  field: FieldDef
  value: string
  onChange: (v: string) => void
}) {
  const [revealed, setRevealed] = useState(false)
  const isPassword = field.field_type === 'password'

  return (
    <div>
      <label className="block text-xs text-vault-text-muted mb-1">{field.label}</label>
      {field.field_type === 'textarea' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          rows={4}
          className={`${inputClass} resize-none font-mono text-xs leading-relaxed`}
        />
      ) : (
        <div className="relative">
          <input
            type={isPassword && !revealed ? 'password' : 'text'}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            className={`${inputClass}${isPassword ? ' pr-10' : ''}`}
          />
          {isPassword && (
            <button
              type="button"
              onClick={() => setRevealed((v) => !v)}
              aria-label={revealed ? t('credentials.hideValue') : t('credentials.showValue')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-vault-text-muted hover:text-vault-text transition-colors px-1"
            >
              {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function GenericFieldsFlow({
  plugin,
  flow,
  onSaved,
  saveAs,
}: {
  plugin: PluginInfo
  flow: CredentialFlow
  onSaved: () => void
  saveAs?: string
}) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  // Only non-empty fields are submitted; optional fields may be left blank.
  const filled: Record<string, string> = {}
  for (const field of flow.fields) {
    const v = values[field.name]?.trim()
    if (v) filled[field.name] = v
  }

  const canSave =
    Object.keys(filled).length > 0 && flow.fields.every((f) => !f.required || filled[f.name])

  const handleSave = async () => {
    if (!canSave) return
    setSaving(true)
    try {
      await api.settings.setGenericCookie(plugin.source_id, filled, saveAs)
      toast.success(t('credentials.savedSite', { source: plugin.name }))
      setValues({})
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      {flow.fields.map((field) => (
        <GenericField
          key={field.name}
          field={field}
          value={values[field.name] ?? ''}
          onChange={(v) => setValues((prev) => ({ ...prev, [field.name]: v }))}
        />
      ))}
      <Button variant="primary" size="md" onClick={handleSave} disabled={saving || !canSave}>
        {saving ? t('credentials.saving') : t('credentials.save')}
      </Button>
    </div>
  )
}
