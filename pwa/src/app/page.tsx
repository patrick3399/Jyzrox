'use client'

import Link from 'next/link'
import useSWR from 'swr'
import { useState } from 'react'
import {
  Search,
  BookOpen,
  Download,
  Tags,
  Settings,
  ArrowRight,
  BookMarked,
  X,
  Palette,
  FolderTree,
  Users,
  Clock,
  PackageOpen,
  FolderInput,
  Key,
  Puzzle,
  Rss,
} from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import type { Gallery, DownloadJob } from '@/lib/types'

const QUICK_LINKS = [
  {
    href: '/e-hentai',
    label: () => t('dashboard.quickLinks.ehentai'),
    desc: () => t('dashboard.quickLinks.ehentaiDesc'),
    icon: Search,
  },
  {
    href: '/pixiv',
    label: () => t('dashboard.quickLinks.pixiv'),
    desc: () => t('dashboard.quickLinks.pixivDesc'),
    icon: Palette,
  },
  {
    href: '/library',
    label: () => t('dashboard.quickLinks.library'),
    desc: () => t('dashboard.quickLinks.libraryDesc'),
    icon: BookOpen,
  },
  {
    href: '/explorer',
    label: () => t('dashboard.quickLinks.explorer'),
    desc: () => t('dashboard.quickLinks.explorerDesc'),
    icon: FolderTree,
  },
  {
    href: '/artists',
    label: () => t('dashboard.quickLinks.artists'),
    desc: () => t('dashboard.quickLinks.artistsDesc'),
    icon: Users,
  },
  {
    href: '/subscriptions',
    label: () => t('dashboard.quickLinks.subscriptions'),
    desc: () => t('dashboard.quickLinks.subscriptionsDesc'),
    icon: Rss,
  },
  {
    href: '/history',
    label: () => t('dashboard.quickLinks.history'),
    desc: () => t('dashboard.quickLinks.historyDesc'),
    icon: Clock,
  },
  {
    href: '/queue',
    label: () => t('dashboard.quickLinks.queue'),
    desc: () => t('dashboard.quickLinks.queueDesc'),
    icon: Download,
  },
  {
    href: '/tags',
    label: () => t('dashboard.quickLinks.tags'),
    desc: () => t('dashboard.quickLinks.tagsDesc'),
    icon: Tags,
  },
  {
    href: '/export',
    label: () => t('dashboard.quickLinks.export'),
    desc: () => t('dashboard.quickLinks.exportDesc'),
    icon: PackageOpen,
  },
  {
    href: '/import',
    label: () => t('dashboard.quickLinks.import'),
    desc: () => t('dashboard.quickLinks.importDesc'),
    icon: FolderInput,
  },
  {
    href: '/credentials',
    label: () => t('dashboard.quickLinks.credentials'),
    desc: () => t('dashboard.quickLinks.credentialsDesc'),
    icon: Key,
  },
  {
    href: '/plugins',
    label: () => t('dashboard.quickLinks.plugins'),
    desc: () => t('dashboard.quickLinks.pluginsDesc'),
    icon: Puzzle,
  },
  {
    href: '/settings',
    label: () => t('dashboard.quickLinks.settings'),
    desc: () => t('dashboard.quickLinks.settingsDesc'),
    icon: Settings,
  },
]

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

function SystemAlerts({ alerts }: { alerts: string[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set()
    try {
      const stored = sessionStorage.getItem(DISMISSED_KEY)
      return stored ? new Set(JSON.parse(stored) as string[]) : new Set()
    } catch {
      return new Set()
    }
  })

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

  const { data: alertsData } = useSWR(
    'dashboard/alerts',
    () => api.settings.getAlerts(),
    { revalidateOnFocus: false, dedupingInterval: 60000 },
  )

  const alerts = alertsData?.alerts ?? []

  const activeJobs = (jobsData?.jobs ?? []).filter(
    (j: DownloadJob) => j.status === 'queued' || j.status === 'running',
  )

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
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {QUICK_LINKS.map((link) => {
            const Icon = link.icon
            return (
              <Link
                key={link.href}
                href={link.href}
                className="bg-vault-card border border-vault-border rounded-lg p-4 hover:border-vault-border-hover hover:bg-vault-card-hover transition-colors group"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon
                    size={16}
                    className="text-vault-text-muted group-hover:text-vault-accent transition-colors"
                  />
                  <p className="font-medium text-sm">{link.label()}</p>
                </div>
                <p className="text-xs text-vault-text-muted">{link.desc()}</p>
              </Link>
            )
          })}
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

          {libraryLoading && (
            <div className="flex justify-center py-12">
              <LoadingSpinner />
            </div>
          )}

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
