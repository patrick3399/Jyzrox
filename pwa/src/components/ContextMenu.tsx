'use client'
import dynamic from 'next/dynamic'
import type { LucideIcon } from 'lucide-react'
import { t } from '@/lib/i18n'
import { useOpenedOnce } from '@/hooks/useOpenedOnce'

// Every gallery card mounts one of these; load Base UI Menu on first open only.
const AnchoredMenu = dynamic(
  () => import('@/components/ui/menu').then((module) => module.AnchoredMenu),
  {
    ssr: false,
  },
)

export interface ContextMenuItem {
  label: string
  icon?: LucideIcon
  className?: string
  onClick: () => void
}

interface ContextMenuProps {
  open: boolean
  onClose: () => void
  position: { x: number; y: number }
  items: ContextMenuItem[]
}

export function ContextMenu({ open, onClose, position, items }: ContextMenuProps) {
  const opened = useOpenedOnce(open)
  if (!opened) return null
  return (
    <AnchoredMenu
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose()
      }}
      x={position.x}
      y={position.y}
      ariaLabel={t('common.contextMenu')}
      items={items.map((item, i) => ({
        id: String(i),
        label: item.label,
        icon: item.icon,
        danger: item.className?.includes('red') ?? false,
        onSelect: item.onClick,
      }))}
    />
  )
}
