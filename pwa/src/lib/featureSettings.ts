import { mutate as globalMutate } from 'swr'
import { api } from '@/lib/api'

export const FEATURE_SETTINGS_SWR_KEY = 'settings/features'

type FeatureSettings = Awaited<ReturnType<typeof api.settings.getFeatures>>

export async function setFeatureAndSyncCache(feature: string, enabled: boolean): Promise<void> {
  await api.settings.setFeature(feature, enabled)
  await globalMutate<FeatureSettings>(
    FEATURE_SETTINGS_SWR_KEY,
    (current) => (current ? { ...current, [feature]: enabled } : current),
    { revalidate: false },
  )
}
