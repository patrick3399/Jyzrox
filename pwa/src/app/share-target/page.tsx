'use client'

import { useSearchParams, useRouter } from 'next/navigation'
import { useState, useEffect, Suspense } from 'react'
import { Share2, Download, ArrowLeft, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

function detectSource(url: string): string {
  if (url.includes('pixiv.net')) return 'Pixiv'
  if (url.includes('e-hentai.org') || url.includes('exhentai.org')) return 'E-Hentai'
  return 'Unknown'
}

function extractUrl(params: URLSearchParams): string | null {
  const url = params.get('url')
  if (url && url.startsWith('http')) return url
  const text = params.get('text') || ''
  const match = text.match(/https?:\/\/[^\s]+/)
  return match ? match[0] : null
}

function ShareTargetContent() {
  const searchParams = useSearchParams()
  const router = useRouter()

  const [downloading, setDownloading] = useState(false)
  const detectedUrl = extractUrl(searchParams)
  const source = detectedUrl ? detectSource(detectedUrl) : null

  // Auto-focus the download button when a URL is found
  useEffect(() => {
    if (detectedUrl) {
      document.title = t('share.title')
    }
  }, [detectedUrl])

  async function handleDownload() {
    if (!detectedUrl) return
    setDownloading(true)
    try {
      const result = await api.download.enqueue(detectedUrl)
      toast.success(t('share.queued'))
      // Show job ID in a second toast for traceability
      if (result.job_id && !result.job_id.startsWith('offline-')) {
        toast.info(t('share.queuedJob', { jobId: result.job_id }))
      }
      if (window.history.length > 1) {
        router.back()
      } else {
        window.close()
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t('share.failed')
      toast.error(message)
      setDownloading(false)
    }
  }

  return (
    <div className="min-h-screen bg-vault-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 rounded-lg bg-vault-accent">
            <Share2 className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-white">{t('share.title')}</h1>
            <p className="text-sm text-vault-text-muted">{t('share.subtitle')}</p>
          </div>
        </div>

        {/* Card */}
        <div className="bg-vault-card border border-vault-border rounded-xl p-5 space-y-4">
          {detectedUrl ? (
            <>
              {/* Source badge */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-vault-text-muted">{t('share.source')}:</span>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-vault-accent text-indigo-300">
                  {source}
                </span>
              </div>

              {/* URL preview */}
              <div className="flex items-start gap-2 p-3 rounded-lg bg-vault-bg border border-vault-border">
                <ExternalLink className="w-4 h-4 mt-0.5 shrink-0 text-vault-text-muted" />
                <span className="text-sm text-white break-all line-clamp-3">{detectedUrl}</span>
              </div>

              {/* Actions */}
              <div className="flex gap-3 pt-1">
                <button
                  onClick={handleDownload}
                  disabled={downloading}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-medium text-sm transition-colors"
                >
                  <Download className="w-4 h-4" />
                  {downloading ? t('share.downloading') : t('share.download')}
                </button>

                <button
                  onClick={() => router.push('/')}
                  disabled={downloading}
                  className="px-4 py-3 rounded-lg bg-vault-accent hover:bg-vault-border disabled:opacity-60 disabled:cursor-not-allowed text-vault-text-muted text-sm transition-colors"
                  aria-label={t('share.cancel')}
                >
                  <ArrowLeft className="w-4 h-4" />
                </button>
              </div>
            </>
          ) : (
            /* No URL state */
            <>
              <div className="text-center py-4 space-y-2">
                <p className="text-white font-medium">{t('share.noUrl')}</p>
                <p className="text-sm text-vault-text-muted">{t('share.noUrlHint')}</p>
              </div>

              <button
                onClick={() => router.push('/')}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-vault-accent hover:bg-vault-border text-vault-text-muted text-sm transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                {t('share.cancel')}
              </button>
            </>
          )}
        </div>

        {/* View queue link — shown after a successful queue if user didn't redirect */}
        <p className="text-center mt-4">
          <button
            onClick={() => router.push('/queue')}
            className="text-xs text-vault-text-muted hover:text-white transition-colors underline underline-offset-2"
          >
            {t('share.viewQueue')}
          </button>
        </p>
      </div>
    </div>
  )
}

export default function ShareTargetPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-vault-bg flex items-center justify-center">
          <div className="flex items-center gap-3 text-vault-text-muted">
            <Share2 className="w-5 h-5 animate-pulse" />
            <span className="text-sm">{t('common.loading')}</span>
          </div>
        </div>
      }
    >
      <ShareTargetContent />
    </Suspense>
  )
}
