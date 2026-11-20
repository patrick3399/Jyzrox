'use client'

import Link from 'next/link'
import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import { galleryHref } from '@/lib/galleryRoutes'
import { t } from '@/lib/i18n'
import { AppImage } from '@/components/AppImage'
import type { Gallery } from '@/lib/types'
import { Button } from '@/components/ui/button'

const DISMISSED_KEY = 'dashboard:dismissed_alerts'

function alertSeverity(msg: string): 'error' | 'warning' | 'info' {
  const lower = msg.toLowerCase()
  if (
    lower.includes('invalid') ||
    lower.includes('failed') ||
    lower.includes('sad panda') ||
    lower.includes('error') ||
    lower.includes('unauthorized')
  )
    return 'error'
  if (lower.includes('expir') || lower.includes('warning') || lower.includes('expiring'))
    return 'warning'
  return 'info'
}

function alertStyles(severity: 'error' | 'warning' | 'info') {
  if (severity === 'error')
    return {
      wrap: 'bg-red-500/10 border-red-500/30 text-red-300',
      btn: 'text-red-400 hover:text-red-200',
    }
  if (severity === 'warning')
    return {
      wrap: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-300',
      btn: 'text-yellow-400 hover:text-yellow-200',
    }
  return {
    wrap: 'bg-blue-500/10 border-blue-500/30 text-blue-300',
    btn: 'text-blue-400 hover:text-blue-200',
  }
}

export function SystemAlerts({
  alerts,
  onDismiss,
}: {
  alerts: string[]
  onDismiss: (message: string) => void
}) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(DISMISSED_KEY)
      if (stored) setDismissed(new Set(JSON.parse(stored) as string[]))
    } catch {
      // sessionStorage unavailable
    }
  }, [])

  const dismiss = (msg: string) => {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(msg)
      try {
        sessionStorage.setItem(DISMISSED_KEY, JSON.stringify([...next]))
      } catch {
        // sessionStorage unavailable — dismiss only for this render
      }
      return next
    })
    onDismiss(msg)
  }

  const visible = [...new Set(alerts)].filter((a) => !dismissed.has(a))
  if (visible.length === 0) return null

  return (
    <div className="space-y-2">
      {visible.map((msg) => {
        const severity = alertSeverity(msg)
        const styles = alertStyles(severity)
        return (
          <div
            key={msg}
            className={`flex items-center justify-between gap-3 border rounded-lg px-4 py-3 text-sm ${styles.wrap}`}
          >
            <span className="leading-snug">{msg}</span>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => dismiss(msg)}
              className={`shrink-0 ${styles.btn}`}
              aria-label={t('common.dismissAlert')}
            >
              <X size={14} />
            </Button>
          </div>
        )
      })}
    </div>
  )
}

export function GalleryThumb({ gallery }: { gallery: Gallery }) {
  return (
    <Link href={galleryHref(gallery.source, gallery.source_id)} className="group block">
      <div className="aspect-[2/3] bg-vault-card rounded-lg overflow-hidden border border-vault-border group-hover:border-vault-border-hover transition-colors relative">
        {gallery.cover_thumb ? (
          <AppImage
            src={gallery.cover_thumb}
            alt={gallery.title || 'Untitled'}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-vault-text-muted text-xs">
            {gallery.pages}p
          </div>
        )}
      </div>
      <p className="mt-1.5 text-xs text-vault-text-secondary line-clamp-2 leading-snug group-hover:text-vault-text transition-colors">
        {gallery.title || 'Untitled'}
      </p>
      <p className="text-[10px] text-vault-text-muted mt-0.5 capitalize">{gallery.source}</p>
    </Link>
  )
}
