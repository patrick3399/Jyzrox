import { SettingsLayoutShell } from '@/components/settings/SettingsLayoutShell'

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <SettingsLayoutShell>{children}</SettingsLayoutShell>
}
