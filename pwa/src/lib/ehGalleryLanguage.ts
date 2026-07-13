import type { EhGallery } from '@/lib/types'

const LANGUAGE_CODES: Record<string, string> = {
  chinese: 'ZH',
  dutch: 'NL',
  english: 'EN',
  french: 'FR',
  german: 'DE',
  hungarian: 'HU',
  italian: 'IT',
  japanese: 'JA',
  korean: 'KO',
  polish: 'PL',
  portuguese: 'PT',
  russian: 'RU',
  spanish: 'ES',
  thai: 'TH',
  vietnamese: 'VI',
}

const TITLE_LANGUAGE_PATTERNS: Array<[string, RegExp]> = [
  ['EN', /[(\[]eng(?:lish)?[)\]]|英訳/i],
  ['ZH', /[(（\[]ch(?:inese)?[)）\]]|[汉漢]化|中[国國][语語]|中文|中国翻訳/i],
  ['ES', /[(\[](?:spanish|español)[)\]]|スペイン翻訳/i],
  ['KO', /[(\[]korean?[)\]]|韓国翻訳/i],
  ['RU', /[(\[]rus(?:sian)?[)\]]|ロシア翻訳/i],
  ['FR', /[(\[]fr(?:ench)?[)\]]|フランス翻訳/i],
  ['PT', /[(\[]portuguese[)\]]|ポルトガル翻訳/i],
  ['TH', /[(\[]thai(?: ภาษาไทย)?[)\]]|แปลไทย|タイ翻訳/i],
  ['DE', /[(\[]german[)\]]|ドイツ翻訳/i],
  ['IT', /[(\[]italiano?[)\]]|イタリア翻訳/i],
  ['VI', /[(\[]vietnamese(?: Tiếng Việt)?[)\]]|ベトナム翻訳/i],
  ['PL', /[(\[]polish[)\]]|ポーランド翻訳/i],
  ['HU', /[(\[]hun(?:garian)?[)\]]|ハンガリー翻訳/i],
  ['NL', /[(\[]dutch[)\]]|オランダ翻訳/i],
]

export function getEhGalleryLanguage(gallery: Pick<EhGallery, 'tags' | 'title'>): string | null {
  for (const tag of gallery.tags) {
    if (!tag.startsWith('language:')) continue
    const code = LANGUAGE_CODES[tag.slice('language:'.length).toLowerCase()]
    if (code) return code
  }

  for (const [code, pattern] of TITLE_LANGUAGE_PATTERNS) {
    if (pattern.test(gallery.title)) return code
  }
  return null
}
