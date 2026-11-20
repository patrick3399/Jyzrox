'use client'

import { Activity, Zap, HardDrive, CheckCircle2, Loader2 } from 'lucide-react'
import { t } from '@/lib/i18n'
import type { DashboardSiteStats } from '@/lib/types'
import { formatMs, getSiteStatus } from '@/components/admin/dashboard/helpers'

export function GlobalBar({
  running,
  queued,
  today,
  boostMode,
  diskOk,
  diskFreeGb,
  onToggleBoost,
  toggling,
}: {
  running: number
  queued: number
  today: number
  boostMode: boolean
  diskOk: boolean
  diskFreeGb: number
  onToggleBoost: () => void
  toggling: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-vault-card border border-vault-border text-sm">
        <Activity size={14} className="text-blue-400" />
        <span className="text-vault-text-secondary">{t('downloadDashboard.running')}</span>
        <span className="font-semibold text-vault-text">{running}</span>
      </div>
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-vault-card border border-vault-border text-sm">
        <Loader2 size={14} className="text-vault-text-muted" />
        <span className="text-vault-text-secondary">{t('downloadDashboard.queued')}</span>
        <span className="font-semibold text-vault-text">{queued}</span>
      </div>
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-vault-card border border-vault-border text-sm">
        <CheckCircle2 size={14} className="text-green-400" />
        <span className="text-vault-text-secondary">{t('downloadDashboard.today')}</span>
        <span className="font-semibold text-vault-text">{today}</span>
      </div>

      {/* Boost mode toggle */}
      <button
        onClick={onToggleBoost}
        disabled={toggling}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm transition-colors ${
          boostMode
            ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/20'
            : 'bg-vault-card border-vault-border text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover'
        }`}
        title={boostMode ? t('downloadDashboard.boostModeOn') : t('downloadDashboard.boostModeOff')}
      >
        <Zap size={14} />
        <span>{t('downloadDashboard.boostMode')}</span>
        <span className="font-semibold">
          {boostMode ? t('downloadDashboard.toggleBoostOff') : t('downloadDashboard.toggleBoostOn')}
        </span>
      </button>

      {/* Disk indicator */}
      <div
        className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm ${
          diskOk
            ? 'bg-vault-card border-vault-border text-vault-text-secondary'
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        }`}
      >
        <HardDrive size={14} />
        <span>{diskOk ? t('downloadDashboard.diskOk') : t('downloadDashboard.diskLow')}</span>
        <span className="font-semibold">
          {t('downloadDashboard.diskFreeGb', { gb: diskFreeGb.toFixed(1) })}
        </span>
      </div>
    </div>
  )
}

export function SiteTable({ siteStats }: { siteStats: Record<string, DashboardSiteStats> }) {
  const entries = Object.entries(siteStats)
  if (entries.length === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wider mb-3">
        {t('downloadDashboard.siteTable')}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-vault-text-muted text-xs uppercase tracking-wider border-b border-vault-border">
              <th className="text-left pb-2 pr-4">{t('downloadDashboard.site')}</th>
              <th className="text-left pb-2 pr-4">{t('downloadDashboard.slots')}</th>
              <th className="text-right pb-2 pr-4">{t('downloadDashboard.queue')}</th>
              <th className="text-right pb-2 pr-4">{t('downloadDashboard.speed')}</th>
              <th className="text-right pb-2 pr-4">{t('downloadDashboard.delay')}</th>
              <th className="text-right pb-2">{t('downloadDashboard.status')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-vault-border/50">
            {entries.map(([site, stats]) => {
              const { label, color } = getSiteStatus(stats)
              const slotPct =
                stats.semaphore.max > 0 ? (stats.semaphore.used / stats.semaphore.max) * 100 : 0
              return (
                <tr key={site} className="hover:bg-vault-card-hover/30 transition-colors">
                  <td className="py-2.5 pr-4 font-medium text-vault-text">{site}</td>
                  <td className="py-2.5 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 rounded-full bg-vault-input overflow-hidden">
                        <div
                          className="h-full rounded-full bg-blue-500 transition-all"
                          style={{ width: `${slotPct}%` }}
                        />
                      </div>
                      <span className="text-vault-text-secondary text-xs whitespace-nowrap">
                        {stats.semaphore.used}/{stats.semaphore.max}
                      </span>
                    </div>
                  </td>
                  <td className="py-2.5 pr-4 text-right text-vault-text-secondary">
                    {stats.queued}
                  </td>
                  <td className="py-2.5 pr-4 text-right text-vault-text-secondary">
                    {stats.avg_speed > 0
                      ? t('downloadDashboard.pagesPerSec', {
                          speed: stats.avg_speed.toFixed(2),
                        })
                      : '—'}
                  </td>
                  <td className="py-2.5 pr-4 text-right text-vault-text-secondary">
                    {stats.current_delay_ms > 0 ? formatMs(stats.current_delay_ms) : '—'}
                  </td>
                  <td className={`py-2.5 text-right font-medium ${color}`}>{label}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
