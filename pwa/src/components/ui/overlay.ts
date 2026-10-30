interface OpenChangeDetails {
  reason: string
  event: Event
  cancel: () => void
}

/**
 * One open-change policy for every Base UI overlay.
 * Escape always belongs to the overlay: detail pages bind Escape on window to
 * "go back" (FE-T25), so mark it handled even when the close is refused.
 */
export function overlayOpenChange(onOpenChange: (open: boolean) => void, dismissible = true) {
  return (open: boolean, details: OpenChangeDetails) => {
    if (details.reason === 'escape-key') {
      details.event.preventDefault()
      details.event.stopPropagation()
    }
    if (!open && !dismissible) {
      details.cancel()
      return
    }
    onOpenChange(open)
  }
}
