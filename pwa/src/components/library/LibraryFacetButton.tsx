'use client'

import { useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { ChevronDown } from 'lucide-react'
import { useOpenedOnce } from '@/hooks/useOpenedOnce'
import type { FacetSelection } from '@/lib/queryParser'
import type { GalleryCategoryDef } from '@/lib/types'
import { facetSelectionLabel, type FacetOption } from './LibraryFacetList'

// Base UI Popover stays out of the page's initial JS until a facet first opens.
const LibraryFacetPopover = dynamic(
  () => import('@/components/library/LibraryFacetPopover').then((module) => module.LibraryFacetPopover),
  { ssr: false },
)

interface LibraryFacetButtonProps {
  /** Facet name, shown when nothing is selected. */
  label: string
  options: FacetOption[]
  selection: FacetSelection
  onChange: (selection: FacetSelection) => void
  categoryDefs?: GalleryCategoryDef[]
  /** Reports the popover's open state so the search block keeps itself revealed. */
  onOpenChange?: (open: boolean) => void
}

/** Desktop facet trigger: reflects the selection in its label and opens the facet popover. */
export function LibraryFacetButton({
  label,
  options,
  selection,
  onChange,
  categoryDefs,
  onOpenChange,
}: LibraryFacetButtonProps) {
  const [open, setOpenState] = useState(false)
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const opened = useOpenedOnce(open)
  // The anchor is not a Base UI Trigger, so a second tap counts as an outside
  // press: remember the state at pointer-down to avoid close-then-reopen.
  const openAtPointerDownRef = useRef<boolean | null>(null)

  const setOpen = (next: boolean) => {
    setOpenState(next)
    onOpenChange?.(next)
  }

  const text =
    facetSelectionLabel(selection, (value) => options.find((o) => o.value === value)?.label ?? value) ??
    label
  const active = selection.values.length > 0

  return (
    <>
      <button
        type="button"
        ref={setAnchor}
        onMouseDown={(e) => e.preventDefault()}
        onPointerDownCapture={() => {
          openAtPointerDownRef.current = open
        }}
        onClick={() => {
          const wasOpen = openAtPointerDownRef.current ?? open
          openAtPointerDownRef.current = null
          setOpen(!wasOpen)
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={active ? `${label}: ${text}` : label}
        className={`flex h-8 max-w-56 items-center gap-1.5 rounded-lg border px-3 text-sm transition-colors ${
          active
            ? 'border-vault-accent bg-vault-accent/10 text-vault-accent'
            : 'border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text'
        }`}
      >
        <span className="truncate">{text}</span>
        <ChevronDown size={14} className="shrink-0" />
      </button>
      {opened && (
        <LibraryFacetPopover
          open={open}
          onOpenChange={setOpen}
          anchor={anchor}
          title={label}
          options={options}
          selection={selection}
          onChange={onChange}
          categoryDefs={categoryDefs}
        />
      )}
    </>
  )
}
