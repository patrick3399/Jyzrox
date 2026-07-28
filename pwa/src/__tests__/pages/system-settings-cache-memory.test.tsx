import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'

const cacheStats = {
  total_memory: 11256616,
  total_memory_human: '10.73M',
  total_keys: 1645,
  breakdown: {},
}

vi.mock('@/lib/api', () => ({
  api: {
    system: {
      health: vi.fn(async () => ({
        status: 'ok',
        services: { postgres: 'ok', redis: 'ok' },
      })),
      info: vi.fn(async () => ({
        version: '0.1',
        eh_max_concurrency: 3,
        tag_model_enabled: false,
        versions: { jyzrox: '0.1', python: '3.14.0', fastapi: '0.1' },
      })),
      getCache: vi.fn(async () => cacheStats),
      getStorage: vi.fn(async () => ({ mounts: [] })),
      getReconcileStatus: vi.fn(async () => null),
    },
  },
}))

vi.mock('@/hooks/useAdminGuard', () => ({
  useAdminGuard: () => true,
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => 'en',
}))

vi.mock('@/components/BackButton', () => ({
  BackButton: () => null,
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

import SystemSettingsPage from '@/app/settings/system/page'

describe('system settings cache stats', () => {
  it('renders cache memory as human-readable bytes, not a raw byte count', async () => {
    render(<SystemSettingsPage />)

    // 11256616 bytes → "10.7 MiB"; the raw integer must never reach the UI.
    await waitFor(() => {
      expect(screen.getByText('10.7 MiB')).toBeInTheDocument()
    })
    expect(screen.queryByText(String(cacheStats.total_memory))).not.toBeInTheDocument()
  })
})
