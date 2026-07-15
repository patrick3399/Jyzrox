export const CRON_PRESETS = [
  { label: '2h', value: '0 */2 * * *' },
  { label: '6h', value: '0 */6 * * *' },
  { label: '1d', value: '0 0 * * *' },
  { label: '3d', value: '0 0 */3 * *' },
  { label: '1w', value: '0 0 * * 1' },
] as const
