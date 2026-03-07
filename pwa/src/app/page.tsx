'use client'

import Link from 'next/link'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import type { Gallery, DownloadJob } from '@/lib/types'

const QUICK_LINKS = [
  { href: '/browse', label: 'Browse E-Hentai', desc: 'Search and download galleries' },
  { href: '/library', label: 'Library', desc: 'Browse your local collection' },
  { href: '/queue', label: 'Download Queue', desc: 'Manage active downloads' },
  { href: '/tags', label: 'Tags', desc: 'Manage tags, aliases & implications' },
  { href: '/settings', label: 'Settings', desc: 'Credentials and system config' },
]

function GalleryThumb({ gallery }: { gallery: Gallery }) {
  return (
    <Link href={`/library/${gallery.id}`} className="group block">
      <div className="aspect-[2/3] bg-[#1a1a1a] rounded-lg overflow-hidden border border-[#2a2a2a] group-hover:border-[#444] transition-colors relative">
        <div className="absolute inset-0 flex items-center justify-center text-gray-600 text-xs">
          {gallery.pages}p
        </div>
      </div>
      <p className="mt-1.5 text-xs text-gray-300 line-clamp-2 leading-snug group-hover:text-white transition-colors">
        {gallery.title || 'Untitled'}
      </p>
      <p className="text-[10px] text-gray-600 mt-0.5 capitalize">{gallery.source}</p>
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
    { refreshInterval: 5000 }
  )

  const { data: healthData } = useSWR(
    'dashboard/health',
    () => api.system.health().catch(() => null),
    { refreshInterval: 30000 }
  )

  const activeJobs = (jobsData?.jobs ?? []).filter(
    (j: DownloadJob) => j.status === 'queued' || j.status === 'running'
  )

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-8">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-sm text-gray-500 mt-0.5">Jyzrox rev 2.0</p>
          </div>
          {healthData && (
            <div className="flex items-center gap-1.5 text-xs text-green-400">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              System online
            </div>
          )}
        </div>

        {/* Quick Links */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {QUICK_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="bg-[#111111] border border-[#2a2a2a] rounded-lg p-4 hover:border-[#444] hover:bg-[#161616] transition-colors"
            >
              <p className="font-medium text-sm text-white mb-1">{link.label}</p>
              <p className="text-xs text-gray-500">{link.desc}</p>
            </Link>
          ))}
        </div>

        {/* Active Downloads */}
        {activeJobs.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
                Active Downloads ({activeJobs.length})
              </h2>
              <Link href="/queue" className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
                View all →
              </Link>
            </div>
            <div className="space-y-2">
              {activeJobs.map((job: DownloadJob) => (
                <div key={job.id} className="bg-[#111111] border border-[#2a2a2a] rounded-lg px-4 py-3 flex items-center justify-between gap-3">
                  <p className="text-sm text-gray-300 truncate">{job.url}</p>
                  <span className={`flex-shrink-0 text-xs font-medium px-2 py-0.5 rounded border ${
                    job.status === 'running'
                      ? 'bg-blue-900/40 border-blue-700/50 text-blue-400'
                      : 'bg-yellow-900/40 border-yellow-700/50 text-yellow-400'
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
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
              Recently Added
              {libraryData && (
                <span className="ml-2 text-gray-600 normal-case font-normal">
                  ({libraryData.total.toLocaleString()} total)
                </span>
              )}
            </h2>
            <Link href="/library" className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
              View library →
            </Link>
          </div>

          {libraryLoading && (
            <div className="flex justify-center py-12">
              <LoadingSpinner />
            </div>
          )}

          {!libraryLoading && libraryData && libraryData.galleries.length === 0 && (
            <div className="bg-[#111111] border border-[#2a2a2a] rounded-lg p-8 text-center text-gray-600">
              <p className="text-sm">No galleries yet.</p>
              <p className="text-xs mt-1">
                <Link href="/browse" className="text-blue-400 hover:underline">Browse E-Hentai</Link>
                {' '}to download your first gallery.
              </p>
            </div>
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
