'use client'

import { useParams } from 'next/navigation'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AppImage } from '@/components/AppImage'

export default function PublicGallerySharePage() {
  const params = useParams<{ token: string }>()
  const token = params.token
  const { data, error, isLoading } = useSWR(token ? ['public-share', token] : null, () => api.galleryManagement.publicShare(token))

  if (isLoading) return <div className="flex min-h-screen items-center justify-center"><LoadingSpinner /></div>
  if (error || !data) return <main className="mx-auto max-w-xl p-8 text-center text-vault-text">This share link is unavailable or has expired.</main>

  return (
    <main className="mx-auto max-w-6xl p-4 md:p-8">
      <header className="mb-6">
        <p className="text-xs uppercase tracking-wide text-vault-text-muted">Shared from Jyzrox</p>
        <h1 className="text-2xl font-bold text-vault-text">{data.gallery.title || 'Untitled gallery'}</h1>
        <p className="text-sm text-vault-text-muted">{data.gallery.pages} images</p>
      </header>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {data.images.map((image) => (
          <AppImage key={image.id} src={image.url} alt={`Page ${image.page_num}`} loading="lazy" className="h-auto w-full rounded-lg bg-vault-card object-contain" />
        ))}
      </div>
    </main>
  )
}
