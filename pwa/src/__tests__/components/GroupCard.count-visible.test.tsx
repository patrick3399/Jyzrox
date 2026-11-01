import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/components/subscriptions/SubscriptionCard', () => ({
  SubscriptionCard: () => null,
  timeAgo: () => '',
}))

import { GroupCard } from '@/components/subscriptions/GroupCard'

const noop = vi.fn()

function renderCard(props: Record<string, unknown>) {
  return render(
    <GroupCard
      group={null}
      subs={[]}
      jobsData={{}}
      groups={[]}
      onEdit={noop}
      onRun={noop}
      onPauseResume={noop}
      onDelete={noop}
      onToggleSub={noop}
      onCheckSub={noop}
      onBackfillSub={noop}
      onDeleteSub={noop}
      onAutoDownloadToggle={noop}
      onMoveToGroup={noop}
      onRenameSub={noop}
      checkingId={null}
      defaultExpanded={false}
      {...props}
    />,
  )
}

describe('GroupCard — subscription count', () => {
  it('test_groupCard_sectionCountNotHiddenBelowSmBreakpoint', () => {
    renderCard({ title: 'pixiv' })
    const count = screen.getByTestId('group-sub-count')
    expect(count.className).not.toMatch(/\bhidden\b/)
    expect(count.className).not.toMatch(/sm:/)
  })
})
