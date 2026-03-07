interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const sizeMap = {
  sm: 'w-4 h-4 border-2',
  md: 'w-8 h-8 border-2',
  lg: 'w-12 h-12 border-4',
}

export function LoadingSpinner({ size = 'md', className = '' }: LoadingSpinnerProps) {
  return (
    <div
      className={`
        inline-block rounded-full
        border-gray-600 border-t-purple-500
        animate-spin
        ${sizeMap[size]}
        ${className}
      `}
      role="status"
      aria-label="Loading"
    />
  )
}

export function LoadingPage() {
  return (
    <div className="flex items-center justify-center w-full h-full min-h-screen bg-[#111111]">
      <LoadingSpinner size="lg" />
    </div>
  )
}
