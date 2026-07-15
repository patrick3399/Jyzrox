'use client'

import dynamic from 'next/dynamic'

export const LazySauceNaoModal = dynamic(
  () => import('./SauceNaoModal').then((module) => module.SauceNaoModal),
  { ssr: false },
)

export const LazyNovelCreateDialog = dynamic(
  () => import('./novels/NovelCreateDialog').then((module) => module.NovelCreateDialog),
  { ssr: false },
)
