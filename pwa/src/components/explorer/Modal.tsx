'use client'

import { Dialog } from '@/components/ui/dialog'

export function Modal({
  title,
  children,
  footer,
  onClose,
}: {
  title: string
  children: React.ReactNode
  footer?: React.ReactNode
  onClose: () => void
}) {
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      title={title}
      size="lg"
      padded={false}
      footer={footer}
    >
      {children}
    </Dialog>
  )
}
