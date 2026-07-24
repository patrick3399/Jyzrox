'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { toast } from 'sonner'
import { useLocale } from '@/components/LocaleProvider'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

export default function TrainingAssetsPage() {
  useLocale()
  const { data, mutate } = useSWR('training/loras', api.training.listLoras)
  const [name, setName] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [triggerWords, setTriggerWords] = useState('')
  const [trainingParams, setTrainingParams] = useState('{}')
  const [loraFile, setLoraFile] = useState<File | null>(null)
  const [comfyFile, setComfyFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)

  const uploadLora = async () => {
    if (!loraFile || !name.trim()) return
    const form = new FormData()
    form.set('file', loraFile)
    form.set('name', name.trim())
    if (datasetId) form.set('dataset_id', datasetId)
    form.set('trigger_words', triggerWords)
    form.set('training_params', trainingParams)
    setBusy(true)
    try {
      await api.training.uploadLora(form)
      toast.success(t('training.uploaded'))
      setLoraFile(null)
      await mutate()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const importComfy = async () => {
    if (!comfyFile) return
    const form = new FormData()
    form.set('file', comfyFile)
    setBusy(true)
    try {
      const result = await api.training.importComfy(form)
      toast.success(t('training.imported', { id: result.gallery_id }))
      setComfyFile(null)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-4 md:p-8">
      <div>
        <h1 className="text-2xl font-bold text-vault-text">{t('training.title')}</h1>
        <p className="text-sm text-vault-text-muted">{t('training.description')}</p>
      </div>

      <section className="rounded-xl border border-vault-border bg-vault-card p-4">
        <h2 className="mb-3 font-semibold text-vault-text">{t('training.uploadLora')}</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <input
            className="rounded border border-vault-border bg-vault-bg p-2"
            placeholder={t('training.modelName')}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <input
            className="rounded border border-vault-border bg-vault-bg p-2"
            placeholder={t('training.datasetIdOptional')}
            inputMode="numeric"
            value={datasetId}
            onChange={(event) => setDatasetId(event.target.value)}
          />
          <input
            className="rounded border border-vault-border bg-vault-bg p-2"
            placeholder={t('training.triggerWords')}
            value={triggerWords}
            onChange={(event) => setTriggerWords(event.target.value)}
          />
          <input
            className="rounded border border-vault-border bg-vault-bg p-2 font-mono"
            placeholder={t('training.paramsJson')}
            value={trainingParams}
            onChange={(event) => setTrainingParams(event.target.value)}
          />
          <input
            type="file"
            accept=".safetensors"
            onChange={(event) => setLoraFile(event.target.files?.[0] ?? null)}
          />
          <button
            className="rounded bg-vault-accent px-4 py-2 text-white disabled:opacity-50"
            disabled={busy || !loraFile || !name.trim()}
            onClick={uploadLora}
          >
            {t('training.upload')}
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-vault-border bg-vault-card p-4">
        <h2 className="mb-3 font-semibold text-vault-text">{t('training.importComfy')}</h2>
        <div className="flex flex-wrap gap-3">
          <input
            type="file"
            accept="image/png,.png"
            onChange={(event) => setComfyFile(event.target.files?.[0] ?? null)}
          />
          <button
            className="rounded bg-vault-accent px-4 py-2 text-white disabled:opacity-50"
            disabled={busy || !comfyFile}
            onClick={importComfy}
          >
            {t('training.importWorkflow')}
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-vault-border bg-vault-card p-4">
        <h2 className="mb-3 font-semibold text-vault-text">{t('training.library')}</h2>
        <div className="space-y-2">
          {(data?.loras ?? []).map((model) => (
            <div
              key={model.id}
              className="flex items-center justify-between gap-3 rounded border border-vault-border p-3"
            >
              <div>
                <p className="font-medium text-vault-text">{model.name}</p>
                <p className="text-xs text-vault-text-muted">
                  {model.trigger_words.join(', ') || t('training.noTriggerWords')} ·{' '}
                  {(model.file_size / 1024 / 1024).toFixed(1)} MB
                </p>
              </div>
              <div className="flex gap-2">
                <a
                  className="rounded border border-vault-border px-3 py-1 text-sm"
                  href={`/api/training/loras/${model.id}/file`}
                >
                  {t('training.download')}
                </a>
                <button
                  className="rounded border border-red-500/40 px-3 py-1 text-sm text-red-400"
                  onClick={async () => {
                    await api.training.deleteLora(model.id)
                    await mutate()
                  }}
                >
                  {t('common.delete')}
                </button>
              </div>
            </div>
          ))}
          {!data?.loras.length && (
            <p className="text-sm text-vault-text-muted">{t('training.empty')}</p>
          )}
        </div>
      </section>
    </main>
  )
}
