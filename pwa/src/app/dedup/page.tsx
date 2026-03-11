import { t } from '@/lib/i18n'
import { DedupSettingsCard } from '@/components/Dedup/DedupSettingsCard'
import { ReviewList } from '@/components/Dedup/ReviewList'

export default function DedupPage() {
  return (
    <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-vault-text">{t('dedup.title')}</h1>
        <p className="text-sm text-vault-text-muted mt-1">{t('dedup.subtitle')}</p>
      </div>
      <DedupSettingsCard />
      <ReviewList />
    </main>
  )
}
