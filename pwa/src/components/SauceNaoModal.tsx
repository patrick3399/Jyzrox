'use client'

import { useState, useEffect } from 'react'
import { X, Loader2, Search, ExternalLink, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import type { SauceNaoResult } from '@/lib/api'
import { t } from '@/lib/i18n'

export function SauceNaoModal({
  imageId,
  onClose,
}: {
  imageId: number
  onClose: () => void
}) {
  const [results, setResults] = useState<SauceNaoResult[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setResults(null)

    api.saucenao
      .search(imageId)
      .then((data) => {
        if (!cancelled) setResults(data.results)
      })
      .catch((err) => {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : String(err)
        if (msg.includes('saucenao_not_configured')) {
          setError('not_configured')
        } else if (msg.includes('rate_limit')) {
          setError('rate_limited')
        } else {
          setError('generic')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [imageId])

  const errorMessage =
    error === 'not_configured'
      ? t('saucenao.notConfigured')
      : error === 'rate_limited'
        ? t('saucenao.rateLimited')
        : error
          ? t('saucenao.error')
          : null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-vault-card border border-vault-border rounded-xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-vault-border">
          <div className="flex items-center gap-2">
            <Search size={14} className="text-vault-accent" />
            <h3 className="text-sm font-semibold text-vault-text">{t('saucenao.title')}</h3>
          </div>
          <button
            onClick={onClose}
            className="text-vault-text-muted hover:text-vault-text transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="flex flex-col items-center justify-center py-8 gap-2">
              <Loader2 className="animate-spin text-vault-text-muted" size={24} />
              <p className="text-sm text-vault-text-muted">{t('saucenao.searching')}</p>
            </div>
          )}

          {errorMessage && (
            <div className="flex flex-col items-center py-8 gap-2">
              <AlertCircle size={24} className="text-red-400" />
              <p className="text-sm text-red-400 text-center">{errorMessage}</p>
            </div>
          )}

          {results && results.length === 0 && (
            <div className="flex flex-col items-center py-8 gap-2">
              <Search size={24} className="text-vault-text-muted" />
              <p className="text-sm text-vault-text-muted">{t('saucenao.noResults')}</p>
            </div>
          )}

          {results && results.length > 0 && (
            <div className="space-y-2">
              {results.map((r, i) => (
                <ResultItem key={i} result={r} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ResultItem({ result }: { result: SauceNaoResult }) {
  const similarityColor =
    result.similarity >= 90
      ? 'text-green-400'
      : result.similarity >= 70
        ? 'text-yellow-400'
        : 'text-vault-text-muted'

  return (
    <div className="flex gap-3 p-3 bg-vault-bg/50 border border-vault-border rounded-lg hover:border-vault-border-hover transition-colors">
      {/* Thumbnail */}
      {result.thumbnail && (
        <img
          src={result.thumbnail}
          alt=""
          className="w-16 h-16 object-cover rounded flex-shrink-0 bg-vault-bg"
          loading="lazy"
        />
      )}

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={`text-xs font-mono font-semibold ${similarityColor}`}>
            {t('saucenao.similarity', { value: result.similarity.toFixed(1) })}
          </span>
        </div>

        {result.title && (
          <p className="text-sm text-vault-text truncate">{result.title}</p>
        )}

        {result.author && (
          <p className="text-xs text-vault-text-muted truncate">{result.author}</p>
        )}

        <p className="text-xs text-vault-text-muted truncate mt-0.5">{result.source_name}</p>
      </div>

      {/* Link */}
      {result.source_url && (
        <a
          href={result.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center self-center p-2 text-vault-accent hover:text-vault-accent/80 transition-colors"
          title={t('saucenao.openLink')}
        >
          <ExternalLink size={16} />
        </a>
      )}
    </div>
  )
}
