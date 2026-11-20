'use client'

import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import useSWR from 'swr'
import { t } from '@/lib/i18n'
import { api } from '@/lib/api'

type EventCategory = 'all' | 'download' | 'gallery' | 'import' | 'system'

function getEventCategory(eventType: string): EventCategory {
  if (eventType.startsWith('download')) return 'download'
  if (eventType.startsWith('gallery')) return 'gallery'
  if (eventType.startsWith('import')) return 'import'
  return 'system'
}

const EVENT_CATEGORY_COLORS: Record<EventCategory, string> = {
  all: 'bg-vault-input text-vault-text-secondary',
  download: 'bg-blue-500/10 text-blue-400',
  gallery: 'bg-purple-500/10 text-purple-400',
  import: 'bg-green-500/10 text-green-400',
  system: 'bg-orange-500/10 text-orange-400',
}

function eventBadgeClass(eventType: string): string {
  const cat = getEventCategory(eventType)
  return EVENT_CATEGORY_COLORS[cat]
}

export function RecentEvents() {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<EventCategory>('all')
  const { data } = useSWR(open ? 'system/events' : null, () => api.system.getEvents(50), {
    refreshInterval: 10000,
  })

  const categories: EventCategory[] = ['all', 'download', 'gallery', 'import', 'system']
  const filtered =
    data?.events.filter((e) => filter === 'all' || getEventCategory(e.event_type) === filter) ?? []

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      {/* Collapsible header */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-vault-card-hover/30 transition-colors"
      >
        <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wider">
          {t('adminEvents.title')}
        </h2>
        <ChevronDown
          size={16}
          className={`text-vault-text-muted transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="border-t border-vault-border">
          {/* Category filter chips */}
          <div className="flex flex-wrap gap-1.5 px-4 pt-3 pb-2">
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setFilter(cat)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                  filter === cat
                    ? 'bg-vault-accent text-white'
                    : 'bg-vault-input text-vault-text-muted hover:text-vault-text'
                }`}
              >
                {t(
                  `adminEvents.filter${cat.charAt(0).toUpperCase()}${cat.slice(1)}` as Parameters<
                    typeof t
                  >[0],
                )}
              </button>
            ))}
          </div>

          {/* Table */}
          <div className="overflow-x-auto px-4 pb-4">
            {filtered.length === 0 ? (
              <p className="text-sm text-vault-text-muted py-4 text-center">
                {t('adminEvents.noEvents')}
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-vault-text-muted text-xs uppercase tracking-wider border-b border-vault-border">
                    <th className="text-left pb-2 pr-4 font-medium">{t('adminEvents.colTime')}</th>
                    <th className="text-left pb-2 pr-4 font-medium">{t('adminEvents.colType')}</th>
                    <th className="text-left pb-2 pr-4 font-medium">
                      {t('adminEvents.colResource')}
                    </th>
                    <th className="text-left pb-2 font-medium">{t('adminEvents.colActor')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-vault-border/50">
                  {filtered.map((event, idx) => (
                    <tr key={idx} className="hover:bg-vault-card-hover/30 transition-colors">
                      <td className="py-2 pr-4 text-vault-text-muted text-xs whitespace-nowrap tabular-nums">
                        {new Date(event.timestamp).toLocaleString()}
                      </td>
                      <td className="py-2 pr-4">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-medium ${eventBadgeClass(event.event_type)}`}
                        >
                          {event.event_type}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-vault-text-secondary text-xs">
                        {event.resource_type && event.resource_id
                          ? `${event.resource_type}:${event.resource_id}`
                          : (event.resource_type ?? '—')}
                      </td>
                      <td className="py-2 text-vault-text-secondary text-xs">
                        {event.actor_user_id != null
                          ? `#${event.actor_user_id}`
                          : t('adminEvents.actorSystem')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────
