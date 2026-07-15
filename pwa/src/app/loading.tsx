import { LoadingSpinner } from '@/components/LoadingSpinner'

export default function Loading() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <LoadingSpinner size="lg" />
    </div>
  )
}
