'use client'

import Link from 'next/link'
import useSWR from 'swr'
import { useState, useCallback, useEffect } from 'react'
import { ArrowRight, BookMarked, X, LayoutList, LayoutGrid } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { SkeletonGrid } from '@/components/Skeleton'
import { EmptyState } from '@/components/EmptyState'
import type { Gallery, DownloadJob } from '@/lib/types'
import { loadDashboardConfig, DASHBOARD_LINKS_CONFIG_KEY } from '@/components/DashboardLinksConfig'

const DISMISSED_KEY = 'dashboard:dismissed_alerts'
const COMPACT_LINKS_KEY = 'dashboard_compact_links'

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

function SystemAlerts({ alerts }: { alerts: string[] }) {
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
  }

  const visible = alerts.filter((a) => !dismissed.has(a))
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
            <button
              onClick={() => dismiss(msg)}
              className={`shrink-0 p-0.5 rounded transition-colors ${styles.btn}`}
              aria-label={t('common.dismissAlert')}
            >
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}

function GalleryThumb({ gallery }: { gallery: Gallery }) {
  return (
    <Link href={`/library/${gallery.source}/${gallery.source_id}`} className="group block">
      <div className="aspect-[2/3] bg-vault-card rounded-lg overflow-hidden border border-vault-border group-hover:border-vault-border-hover transition-colors relative">
        {gallery.cover_thumb ? (
          <img
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

export default function Dashboard() {
  const { data: libraryData, isLoading: libraryLoading } = useSWR('dashboard/recent', () =>
    api.library.getGalleries({ limit: 12, sort: 'added_at' }),
  )

  const { data: jobsData } = useSWR('dashboard/jobs', () => api.download.getJobs({ limit: 5 }), {
    refreshInterval: 5000,
    dedupingInterval: 3000,
    focusThrottleInterval: 10000,
  })

  const { data: alertsData } = useSWR('dashboard/alerts', () => api.settings.getAlerts(), {
    revalidateOnFocus: false,
    dedupingInterval: 60000,
  })

  const alerts = alertsData?.alerts ?? []

  const activeJobs = (jobsData?.jobs ?? []).filter(
    (j: DownloadJob) => j.status === 'queued' || j.status === 'running',
  )

  // Quick links config — user-customisable via Settings > Dashboard Quick Links
  // loadDashboardConfig() is SSR-safe (returns ALL_DASHBOARD_LINKS when window is undefined)
  const [quickLinks, setQuickLinks] = useState(() => loadDashboardConfig())

  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === DASHBOARD_LINKS_CONFIG_KEY) {
        setQuickLinks(loadDashboardConfig())
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  // Compact links state — persisted to localStorage.
  // Default: compact on mobile (< lg = 1024px), expanded on desktop.
  const [compactLinks, setCompactLinks] = useState<boolean>(false)

  useEffect(() => {
    const stored = localStorage.getItem(COMPACT_LINKS_KEY)
    if (stored !== null) {
      setCompactLinks(stored === 'true')
    } else {
      setCompactLinks(window.innerWidth < 1024)
    }
  }, [])

  const toggleCompactLinks = useCallback(() => {
    setCompactLinks((prev) => {
      const next = !prev
      try {
        localStorage.setItem(COMPACT_LINKS_KEY, String(next))
      } catch {
        /* noop */
      }
      return next
    })
  }, [])

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t('dashboard.title')}</h1>
        </div>
      </div>

      {/* System Alerts */}
      {alerts.length > 0 && <SystemAlerts alerts={alerts} />}

      {/* Quick Links */}
      <div>
        {/* Section header with toggle */}
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
            {t('dashboard.quickLinks.title')}
          </h2>
          <button
            onClick={toggleCompactLinks}
            className="p-1.5 rounded-md text-vault-text-muted hover:text-vault-text hover:bg-vault-card-hover transition-colors"
            aria-label={
              compactLinks
                ? t('dashboard.quickLinks.expandedView')
                : t('dashboard.quickLinks.compactView')
            }
            title={
              compactLinks
                ? t('dashboard.quickLinks.expandedView')
                : t('dashboard.quickLinks.compactView')
            }
          >
            {compactLinks ? <LayoutList size={15} /> : <LayoutGrid size={15} />}
          </button>
        </div>

        {/* Grid — animates between compact and expanded */}
        <div
          className={`grid gap-2 transition-all duration-200 ${
            compactLinks
              ? 'grid-cols-4 sm:grid-cols-5 md:grid-cols-7 lg:grid-cols-9 xl:grid-cols-10'
              : 'grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7'
          }`}
        >
          {quickLinks.map((link) => {
            const Icon = link.icon
            if (compactLinks) {
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className="bg-vault-card border border-vault-border rounded-lg p-2 hover:border-vault-border-hover hover:bg-vault-card-hover transition-colors group flex flex-col items-center gap-1.5"
                  title={link.descKey ? t(link.descKey) : t(link.labelKey)}
                >
                  <Icon
                    size={18}
                    className="text-vault-text-muted group-hover:text-vault-accent transition-colors shrink-0"
                  />
                  <p className="text-[10px] text-vault-text-secondary text-center leading-tight font-medium line-clamp-2">
                    {t(link.labelKey)}
                  </p>
                </Link>
              )
            }
            return (
              <Link
                key={link.href}
                href={link.href}
                className="bg-vault-card border border-vault-border rounded-lg p-3 lg:p-4 hover:border-vault-border-hover hover:bg-vault-card-hover transition-colors group flex flex-col items-center lg:items-start gap-1"
              >
                <Icon
                  size={20}
                  className="text-vault-text-muted group-hover:text-vault-accent transition-colors lg:hidden"
                />
                <div className="hidden lg:flex items-center gap-2 mb-1">
                  <Icon
                    size={16}
                    className="text-vault-text-muted group-hover:text-vault-accent transition-colors"
                  />
                  <p className="font-medium text-sm">{t(link.labelKey)}</p>
                </div>
                <p className="text-xs text-vault-text-secondary text-center lg:text-left font-medium lg:font-normal lg:hidden">
                  {t(link.labelKey)}
                </p>
                <p className="text-xs text-vault-text-muted hidden lg:block">
                  {link.descKey ? t(link.descKey) : ''}
                </p>
              </Link>
            )
          })}
        </div>
      </div>

      {/* Active Downloads */}
      {activeJobs.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
              {t('dashboard.activeDownloads')} ({activeJobs.length})
            </h2>
            <Link
              href="/queue"
              className="flex items-center gap-1 text-xs text-vault-accent hover:text-vault-accent/80 transition-colors"
            >
              {t('dashboard.viewAll')} <ArrowRight size={12} />
            </Link>
          </div>
          <div className="space-y-2">
            {activeJobs.map((job: DownloadJob) => (
              <div
                key={job.id}
                className="bg-vault-card border border-vault-border rounded-lg px-4 py-3 flex items-center justify-between gap-3"
              >
                <p className="text-sm text-vault-text-secondary truncate">{job.url}</p>
                <span
                  className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded border ${
                    job.status === 'running'
                      ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                      : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
                  }`}
                >
                  {job.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recently Added */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
            {t('dashboard.recentlyAdded')}
            {libraryData && (
              <span className="ml-2 text-vault-text-muted/60 normal-case font-normal">
                ({(libraryData.total ?? 0).toLocaleString()} {t('dashboard.total')})
              </span>
            )}
          </h2>
          <Link
            href="/library"
            className="flex items-center gap-1 text-xs text-vault-accent hover:text-vault-accent/80 transition-colors"
          >
            {t('dashboard.viewLibrary')} <ArrowRight size={12} />
          </Link>
        </div>

        {libraryLoading && <SkeletonGrid count={12} />}

        {!libraryLoading && libraryData && libraryData.galleries.length === 0 && (
          <EmptyState
            icon={BookMarked}
            title={t('dashboard.noGalleries')}
            description={t('dashboard.noGalleriesHint')}
          />
        )}

        {!libraryLoading && libraryData && libraryData.galleries.length > 0 && (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10 2xl:grid-cols-12 gap-3">
            {libraryData.galleries.map((gallery) => (
              <GalleryThumb key={gallery.id} gallery={gallery} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
