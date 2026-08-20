'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { Download, FolderCog } from 'lucide-react'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'

export default function ExportPage() {
  const { data, isLoading } = useSWR('export-datasets', () => api.datasets.list())
  const [datasetId, setDatasetId] = useState<number | null>(null)
  const [triggerWord, setTriggerWord] = useState('')
  const [validationPercent, setValidationPercent] = useState(10)
  const [includeMetadata, setIncludeMetadata] = useState(true)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (datasetId == null && data?.datasets[0]) setDatasetId(data.datasets[0].id)
  }, [data, datasetId])

  const selected = useMemo(
    () => data?.datasets.find((dataset) => dataset.id === datasetId),
    [data, datasetId],
  )

  const handleExport = () => {
    if (!datasetId) return
    setExporting(true)
    const url = api.export.datasetUrl(datasetId, {
      trigger_word: triggerWord,
      validation_percent: validationPercent,
      include_metadata: includeMetadata,
    })
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = ''
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => setExporting(false), 2000)
  }

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-vault-text">{t('export.title')}</h1>
        <p className="mt-2 text-vault-text-secondary">{t('export.datasetSubtitle')}</p>
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : !data?.datasets.length ? (
        <div className="rounded-xl border border-vault-border bg-vault-card p-8 text-center">
          <FolderCog className="mx-auto mb-3 text-vault-text-muted" />
          <p className="text-vault-text">{t('export.noDatasets')}</p>
          <Link href="/datasets" className="mt-3 inline-block text-sm text-vault-accent hover:underline">
            {t('export.createDataset')}
          </Link>
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)]">
          <section className="rounded-xl border border-vault-border bg-vault-card p-5">
            <h2 className="mb-4 font-semibold text-vault-text">{t('export.chooseDataset')}</h2>
            <div className="space-y-2">
              {data.datasets.map((dataset) => (
                <button
                  type="button"
                  key={dataset.id}
                  onClick={() => setDatasetId(dataset.id)}
                  className={`w-full rounded-lg border p-3 text-left transition-colors ${
                    dataset.id === datasetId
                      ? 'border-vault-accent bg-vault-accent/10'
                      : 'border-vault-border bg-vault-input hover:border-vault-border-hover'
                  }`}
                >
                  <span className="font-medium text-vault-text">{dataset.name}</span>
                  <span className="mt-1 block text-xs text-vault-text-muted">
                    {t('export.datasetStats', {
                      images: String(dataset.member_count),
                      excluded: String(dataset.excluded_count),
                    })}
                  </span>
                </button>
              ))}
            </div>
          </section>

          <section className="space-y-4 rounded-xl border border-vault-border bg-vault-card p-5">
            <h2 className="font-semibold text-vault-text">{t('export.options')}</h2>
            <label className="block text-sm text-vault-text-secondary">
              {t('export.triggerWord')}
              <input
                value={triggerWord}
                onChange={(event) => setTriggerWord(event.target.value)}
                maxLength={200}
                className="mt-1.5 w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
                placeholder={selected?.name ?? ''}
              />
            </label>
            <label className="text-sm text-vault-text-secondary">
              {t('export.validationPercent')}
              <input
                type="number"
                min={0}
                max={50}
                value={validationPercent}
                onChange={(event) => setValidationPercent(Number(event.target.value))}
                className="mt-1.5 w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-vault-text-secondary">
              <input
                type="checkbox"
                checked={includeMetadata}
                onChange={(event) => setIncludeMetadata(event.target.checked)}
              />
              {t('export.includeMetadata')}
            </label>
            <button
              type="button"
              onClick={handleExport}
              disabled={!datasetId || exporting}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-vault-accent px-4 py-2.5 font-medium text-white disabled:opacity-50"
            >
              <Download size={17} />
              {exporting ? t('export.downloading') : t('export.downloadDataset')}
            </button>
          </section>
        </div>
      )}
    </div>
  )
}
