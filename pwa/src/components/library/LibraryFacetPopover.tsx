'use client'

import { Popover } from '@/components/ui/popover'
import type { FacetSelection } from '@/lib/queryParser'
import type { GalleryCategoryDef } from '@/lib/types'
import {
  LibraryFacetList,
  facetGridColumns,
  visibleFacetOptions,
  type FacetColumns,
  type FacetOption,
} from './LibraryFacetList'

// One column stays compact; wider grids keep every option on screen. Capped to the viewport.
const POPOVER_WIDTH: Record<FacetColumns, string> = {
  1: 'w-72',
  2: 'w-[30rem] max-w-[calc(100vw-2rem)]',
  3: 'w-[42rem] max-w-[calc(100vw-2rem)]',
}

interface LibraryFacetPopoverProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  anchor: Element | null
  title: string
  options: FacetOption[]
  selection: FacetSelection
  onChange: (selection: FacetSelection) => void
  categoryDefs?: GalleryCategoryDef[]
}

/** The facet picker popover; loaded on first open so Base UI Popover stays out of /library's first load. */
export function LibraryFacetPopover({
  open,
  onOpenChange,
  anchor,
  title,
  options,
  selection,
  onChange,
  categoryDefs,
}: LibraryFacetPopoverProps) {
  const columns = facetGridColumns(visibleFacetOptions(options, selection).length)
  return (
    <Popover
      open={open}
      onOpenChange={onOpenChange}
      anchor={anchor}
      ariaLabel={title}
      className={`${POPOVER_WIDTH[columns]} p-3`}
    >
      <LibraryFacetList
        options={options}
        selection={selection}
        onChange={onChange}
        categoryDefs={categoryDefs}
        columns={columns}
      />
    </Popover>
  )
}
