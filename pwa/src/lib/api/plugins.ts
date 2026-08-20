import { apiFetch } from './client'

import type { PluginInfo } from '../types'

// ── Plugins ──────────────────────────────────────────────────────────

export const plugins = {
  list: () => apiFetch<{ plugins: PluginInfo[] }>('/api/plugins/'),
}
