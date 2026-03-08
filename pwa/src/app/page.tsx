'use client'

import Link from 'next/link'
import useSWR from 'swr'
import { Search, BookOpen, Download, Tags, Settings, ArrowRight, BookMarked } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import type { Gallery, DownloadJob } from '@/lib/types'

const QUICK_LINKS = [
  { href: '/browse', label: () => t('dashboard.quickLinks.browse'), desc: () => t('dashboard.quickLinks.browseDesc'), icon: Search },
  { href: '/library', label: () => t('dashboard.quickLinks.library'), desc: () => t('dashboard.quickLinks.libraryDesc'), icon: BookOpen },
  { href: '/queue', label: () => t('dashboard.quickLinks.queue'), desc: () => t('dashboard.quickLinks.queueDesc'), icon: Download },
  { href: '/tags', label: () => t('dashboard.quickLinks.tags'), desc: () => t('dashboard.quickLinks.tagsDesc'), icon: Tags },
  { href: '/settings', label: () => t('dashboard.quickLinks.settings'), desc: () => t('dashboard.quickLinks.settingsDesc'), icon: Settings },
]

function GalleryThumb({ gallery }: { gallery: Gallery }) {
  return (
    <Link href={`/library/${gallery.id}`} className="group block">
      <div className="aspect-[2/3] bg-vault-card rounded-lg overflow-hidden border border-vault-border group-hover:border-vault-border-hover transition-colors relative">
        <div className="absolute inset-0 flex items-center justify-center text-vault-text-muted text-xs">
          {gallery.pages}p
        </div>
      </div>
      <p className="mt-1.5 text-xs text-vault-text-secondary line-clamp-2 leading-snug group-hover:text-vault-text transition-colors">
        {gallery.title || 'Untitled'}
      </p>
      <p className="text-[10px] text-vault-text-muted mt-0.5 capitalize">{gallery.source}</p>
    </Link>
  )
}

export default function Dashboard() {
  const { data: libraryData, isLoading: libraryLoading } = useSWR(
    'dashboard/recent',
    () => api.library.getGalleries({ limit: 12, sort: 'added_at' })
  )

  const { data: jobsData } = useSWR(
    'dashboard/jobs',
    () => api.download.getJobs({ limit: 5 }),
    { refreshInterval: 5000, dedupingInterval: 3000, focusThrottleInterval: 10000 }
  )

  const { data: healthData } = useSWR(
    'dashboard/health',
    () => api.system.health().catch(() => null),
    { refreshInterval: 30000, dedupingInterval: 15000, focusThrottleInterval: 30000 }
  )

  const activeJobs = (jobsData?.jobs ?? []).filter(
    (j: DownloadJob) => j.status === 'queued' || j.status === 'running'
  )

  return (
    <div className="min-h-screen">
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">{t('dashboard.title')}</h1>
            <p className="text-sm text-vault-text-muted mt-0.5">{t('dashboard.subtitle')}</p>
          </div>
          {healthData && (
            <div className="flex items-center gap-1.5 text-xs text-green-500">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
              {t('dashboard.systemOnline')}
            </div>
          )}
        </div>

        {/* Quick Links */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {QUICK_LINKS.map((link) => {
            const Icon = link.icon
            return (
              <Link
                key={link.href}
                href={link.href}
                className="bg-vault-card border border-vault-border rounded-lg p-4 hover:border-vault-border-hover hover:bg-vault-card-hover transition-colors group"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon size={16} className="text-vault-text-muted group-hover:text-vault-accent transition-colors" />
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
              <Link href="/queue" className="flex items-center gap-1 text-xs text-vault-accent hover:text-vault-accent/80 transition-colors">
                {t('dashboard.viewAll')} <ArrowRight size={12} />
              </Link>
            </div>
            <div className="space-y-2">
              {activeJobs.map((job: DownloadJob) => (
                <div key={job.id} className="bg-vault-card border border-vault-border rounded-lg px-4 py-3 flex items-center justify-between gap-3">
                  <p className="text-sm text-vault-text-secondary truncate">{job.url}</p>
                  <span className={`flex-shrink-0 text-xs font-medium px-2 py-0.5 rounded border ${
                    job.status === 'running'
                      ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                      : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
                  }`}>
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
                  ({libraryData.total.toLocaleString()} {t('dashboard.total')})
                </span>
              )}
            </h2>
            <Link href="/library" className="flex items-center gap-1 text-xs text-vault-accent hover:text-vault-accent/80 transition-colors">
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
              action={{ label: t('dashboard.quickLinks.browse'), href: '/browse' }}
            />
          )}

          {!libraryLoading && libraryData && libraryData.galleries.length > 0 && (
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-12 gap-3">
              {libraryData.galleries.map((gallery) => (
                <GalleryThumb key={gallery.id} gallery={gallery} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
