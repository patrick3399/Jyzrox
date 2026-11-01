import { apiFetch, qs } from './client'

import type {
  SiteConfigItem,
  ProbeResult,
  SaqJob,
  QueueOverview,
  EgressPersona,
  PersonaTestResult,
} from '../types'

// ── Admin Sites ──────────────────────────────────────────────────────

export const adminSites = {
  list: () => apiFetch<SiteConfigItem[]>('/api/admin/sites'),
  get: (sourceId: string) => apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}`),
  update: (sourceId: string, data: { download?: Record<string, unknown> }) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  probe: (url: string) =>
    apiFetch<ProbeResult>('/api/admin/sites/probe', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  updateFieldMapping: (sourceId: string, fieldMapping: Record<string, string | null>) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}/field-mapping`, {
      method: 'PUT',
      body: JSON.stringify({ field_mapping: fieldMapping }),
    }),
  reset: (sourceId: string, fieldPath: string) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}/reset`, {
      method: 'POST',
      body: JSON.stringify({ field_path: fieldPath }),
    }),
  resetAdaptive: (sourceId: string) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}/reset-adaptive`, {
      method: 'POST',
    }),
}

// ── Admin Queue ────────────────────────────────────────────────────────

export const adminQueue = {
  overview: () => apiFetch<QueueOverview>('/api/admin/queue/'),
  jobs: (params?: { status?: string; function?: string; offset?: number; limit?: number }) =>
    apiFetch<{ jobs: SaqJob[]; total: number }>(
      `/api/admin/queue/jobs${qs(params as Record<string, unknown>)}`,
    ),
  job: (key: string) => apiFetch<SaqJob>(`/api/admin/queue/jobs/${encodeURIComponent(key)}`),
  retryJob: (key: string) =>
    apiFetch<{ status: string }>(`/api/admin/queue/jobs/${encodeURIComponent(key)}/retry`, {
      method: 'POST',
    }),
  abortJob: (key: string) =>
    apiFetch<{ status: string }>(`/api/admin/queue/jobs/${encodeURIComponent(key)}/abort`, {
      method: 'POST',
    }),
}

// ── Admin Egress Personas (ADR 0022) ───────────────────────────────────

export const adminPersonas = {
  list: () => apiFetch<EgressPersona[]>('/api/admin/personas'),
  create: (data: Partial<EgressPersona> & { name: string }) =>
    apiFetch<EgressPersona>('/api/admin/personas', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: number, data: Partial<EgressPersona>) =>
    apiFetch<EgressPersona>(`/api/admin/personas/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  remove: (id: number) => apiFetch<void>(`/api/admin/personas/${id}`, { method: 'DELETE' }),
  bindAccount: (id: number, source: string, account: string) =>
    apiFetch<EgressPersona>(`/api/admin/personas/${id}/accounts/${encodeURIComponent(source)}`, {
      method: 'PUT',
      body: JSON.stringify({ account }),
    }),
  unbindAccount: (id: number, source: string) =>
    apiFetch<void>(`/api/admin/personas/${id}/accounts/${encodeURIComponent(source)}`, {
      method: 'DELETE',
    }),
  test: (id: number) =>
    apiFetch<PersonaTestResult>(`/api/admin/personas/${id}/test`, { method: 'POST' }),
}
