import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { JobStatusBadge } from '@/components/JobStatusBadge'
import { DownloadStatusBadge } from '@/components/DownloadStatusBadge'
import { t } from '@/lib/i18n'
import type { DownloadJob } from '@/lib/types'

const TONE_CLASS = {
  success: 'text-vault-success',
  accent: 'text-vault-accent',
  neutral: 'text-vault-text-secondary',
  warning: 'text-vault-warning',
  danger: 'text-vault-danger',
} as const
type Tone = keyof typeof TONE_CLASS

function expectTone(el: HTMLElement, tone: Tone) {
  expect(el.className).toContain(TONE_CLASS[tone])
  for (const [other, cls] of Object.entries(TONE_CLASS)) {
    if (other !== tone) expect(el.className).not.toContain(cls)
  }
}

const jobCases: [DownloadJob['status'], string, Tone][] = [
  ['queued', 'admin.queue.queued', 'neutral'],
  ['running', 'settings.tasks.statusRunning', 'accent'],
  ['done', 'admin.queue.completed', 'success'],
  ['failed', 'admin.queue.failed', 'danger'],
  ['cancelled', 'queue.gdlStateCancelled', 'neutral'],
  ['paused', 'queue.gdlStatePaused', 'neutral'],
  ['partial', 'library.statusPartial', 'warning'],
]

describe('JobStatusBadge', () => {
  it.each(jobCases)('status %s renders its label with the mapped tone', (status, key, tone) => {
    render(<JobStatusBadge status={status} />)
    const label = t(key)
    expect(label).not.toBe('')
    expectTone(screen.getByText(label), tone)
  })
})

const dlCases: ['complete' | 'partial' | 'proxy_only', string, Tone][] = [
  ['complete', 'library.statusComplete', 'success'],
  ['partial', 'library.statusPartial', 'warning'],
  ['proxy_only', 'library.statusProxyOnly', 'accent'],
]

describe('DownloadStatusBadge', () => {
  it.each(dlCases)('status %s renders its label with the mapped tone', (status, key, tone) => {
    render(<DownloadStatusBadge status={status} />)
    const label = t(key)
    expect(label).not.toBe('')
    expectTone(screen.getByText(label), tone)
  })
})
