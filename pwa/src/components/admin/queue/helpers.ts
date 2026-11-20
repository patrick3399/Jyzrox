export function timeAgo(ms: number | null): string {
  if (!ms) return '—'
  const diff = Date.now() - ms
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  return `${Math.floor(diff / 3600000)}h ago`
}

export function formatUptime(ms: number): string {
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export const STATUSES = [
  'new',
  'queued',
  'active',
  'scheduled',
  'aborting',
  'aborted',
  'failed',
  'complete',
] as const

export const STATUS_STYLES: Record<string, string> = {
  new: 'bg-gray-500/20 text-gray-400',
  queued: 'bg-yellow-500/20 text-yellow-400',
  active: 'bg-blue-500/20 text-blue-400',
  scheduled: 'bg-purple-500/20 text-purple-400',
  aborting: 'bg-orange-500/20 text-orange-400',
  aborted: 'bg-vault-border/50 text-vault-text-muted',
  failed: 'bg-red-500/20 text-red-400',
  complete: 'bg-green-500/20 text-green-400',
}

// ── Sub-components ─────────────────────────────────────────────────────
