'use client'

import { useState } from 'react'

/**
 * True from the first time `open` is true onwards. Lets an overlay's code load
 * on first open while staying mounted afterwards, so its exit animation runs.
 */
export function useOpenedOnce(open: boolean): boolean {
  const [opened, setOpened] = useState(open)
  if (open && !opened) setOpened(true)
  return opened || open
}
