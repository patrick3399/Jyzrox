interface AlertBannerProps {
  alerts: string[]
  onDismiss: (index: number) => void
}

export function AlertBanner({ alerts, onDismiss }: AlertBannerProps) {
  if (alerts.length === 0) return null

  return (
    <div className="fixed top-0 left-0 right-0 z-50 flex flex-col gap-0.5">
      {alerts.map((alert, index) => (
        <div
          key={index}
          className="
            flex items-center justify-between gap-4
            px-4 py-2.5
            bg-orange-950 border-b border-orange-800
            text-orange-200 text-sm
          "
          role="alert"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-orange-400 flex-shrink-0" aria-hidden="true">
              ⚠
            </span>
            <span className="truncate">{alert}</span>
          </div>
          <button
            type="button"
            onClick={() => onDismiss(index)}
            className="
              flex-shrink-0
              w-6 h-6 flex items-center justify-center
              rounded text-orange-400 hover:text-orange-100
              hover:bg-orange-800/60
              transition-colors duration-150
            "
            aria-label="Dismiss alert"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
