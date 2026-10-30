'use client'

import { useState, useEffect } from 'react'
import useSWR from 'swr'
import { useRouter } from 'next/navigation'
import { ShieldCheck, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import type { UserInfo, UserRole } from '@/lib/types'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { AlertDialog } from '@/components/ui/alert-dialog'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export default function AdminUsersPage() {
  useLocale()
  const router = useRouter()
  const { data: profile, isLoading: profileLoading } = useProfile()

  const { data, isLoading, mutate } = useSWR('admin/users', () => api.users.list(), {
    revalidateOnFocus: false,
  })

  // Create dialog state
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState({
    username: '',
    password: '',
    role: 'viewer' as UserRole,
    email: '',
  })

  // Delete dialog state
  const [deleteTarget, setDeleteTarget] = useState<UserInfo | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const isAdmin = profile?.role === 'admin'

  useEffect(() => {
    if (!profileLoading && profile && !isAdmin) {
      router.replace('/forbidden')
    }
  }, [profileLoading, profile, isAdmin, router])

  if (profileLoading || !profile || !isAdmin) {
    return (
      <PageContainer variant="secondary">
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="text-vault-text-secondary text-sm">{t('common.loading')}</div>
        </div>
      </PageContainer>
    )
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    try {
      await api.users.create({
        username: createForm.username,
        password: createForm.password,
        role: createForm.role,
        ...(createForm.email ? { email: createForm.email } : {}),
      })
      toast.success(t('admin.users.created'))
      setShowCreate(false)
      setCreateForm({ username: '', password: '', role: 'viewer', email: '' })
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  const handleRoleChange = async (user: UserInfo, newRole: string) => {
    try {
      await api.users.update(user.id, { role: newRole })
      toast.success(t('admin.users.updated'))
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.users.delete(deleteTarget.id)
      toast.success(t('admin.users.deleted'))
      setDeleteOpen(false)
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  const users = data?.users ?? []

  return (
    <PageContainer variant="secondary">
      <PageHeader
        title={t('admin.users.title')}
        icon={<ShieldCheck size={24} className="text-vault-accent shrink-0" />}
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors text-sm font-medium"
          >
            <Plus size={16} />
            {t('admin.users.addUser')}
          </button>
        }
      />
      <main className="space-y-6">
        {/* Table */}
        <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
          {isLoading ? (
            <div className="p-8 text-center text-vault-text-secondary text-sm">
              {t('common.loading')}
            </div>
          ) : users.length === 0 ? (
            <div className="p-8 text-center text-vault-text-secondary text-sm">
              {t('admin.users.noUsers')}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-vault-border bg-vault-card-hover">
                    <th className="px-4 py-3 text-left text-vault-text-secondary font-medium">
                      {t('admin.users.username')}
                    </th>
                    <th className="px-4 py-3 text-left text-vault-text-secondary font-medium">
                      {t('admin.users.role')}
                    </th>
                    <th className="px-4 py-3 text-left text-vault-text-secondary font-medium hidden sm:table-cell">
                      {t('admin.users.email')}
                    </th>
                    <th className="px-4 py-3 text-left text-vault-text-secondary font-medium hidden md:table-cell">
                      {t('admin.users.lastLogin')}
                    </th>
                    <th className="px-4 py-3 text-right text-vault-text-secondary font-medium">
                      {t('admin.users.actions')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-vault-border">
                  {users.map((user) => {
                    const isSelf = user.username === profile?.username
                    return (
                      <tr key={user.id} className="hover:bg-vault-card-hover transition-colors">
                        <td className="px-4 py-3 text-vault-text font-medium">
                          {user.username}
                          {isSelf && (
                            <span className="ml-2 text-xs text-vault-text-secondary">
                              {t('admin.users.you')}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <select
                            value={user.role}
                            onChange={(e) => handleRoleChange(user, e.target.value)}
                            disabled={isSelf}
                            className="bg-vault-input border border-vault-border rounded-md px-2 py-1 text-sm text-vault-text disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-1 focus:ring-vault-accent"
                            aria-label={t('admin.users.role')}
                          >
                            <option value="admin">{t('admin.users.roleAdmin')}</option>
                            <option value="member">{t('admin.users.roleMember')}</option>
                            <option value="viewer">{t('admin.users.roleViewer')}</option>
                          </select>
                        </td>
                        <td className="px-4 py-3 text-vault-text-secondary hidden sm:table-cell">
                          {user.email ?? '—'}
                        </td>
                        <td className="px-4 py-3 text-vault-text-secondary hidden md:table-cell">
                          {formatDate(user.last_login_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => {
                              setDeleteTarget(user)
                              setDeleteOpen(true)
                            }}
                            disabled={isSelf}
                            className="p-1.5 rounded-lg text-vault-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                            aria-label={t('admin.users.delete')}
                            title={t('admin.users.delete')}
                          >
                            <Trash2 size={15} />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Create User Dialog */}
        <Dialog
          open={showCreate}
          onOpenChange={(o) => {
            if (!o) setShowCreate(false)
          }}
          title={t('admin.users.createTitle')}
          size="md"
          footer={
            <>
              <Button onClick={() => setShowCreate(false)}>{t('admin.users.cancel')}</Button>
              <Button type="submit" form="create-user-form" variant="primary" disabled={creating}>
                {t('admin.users.create')}
              </Button>
            </>
          }
        >
          <form id="create-user-form" onSubmit={handleCreate} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-vault-text">
                    {t('admin.users.username')}
                  </label>
                  <input
                    type="text"
                    required
                    value={createForm.username}
                    onChange={(e) => setCreateForm((f) => ({ ...f, username: e.target.value }))}
                    className="w-full bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-sm text-vault-text placeholder-vault-text-secondary focus:outline-none focus:ring-1 focus:ring-vault-accent"
                    placeholder={t('admin.users.username')}
                    autoComplete="off"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-vault-text">
                    {t('admin.users.password')}
                  </label>
                  <input
                    type="password"
                    required
                    value={createForm.password}
                    onChange={(e) => setCreateForm((f) => ({ ...f, password: e.target.value }))}
                    className="w-full bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-sm text-vault-text placeholder-vault-text-secondary focus:outline-none focus:ring-1 focus:ring-vault-accent"
                    placeholder={t('admin.users.password')}
                    autoComplete="new-password"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-vault-text">
                    {t('admin.users.role')}
                  </label>
                  <select
                    value={createForm.role}
                    onChange={(e) =>
                      setCreateForm((f) => ({ ...f, role: e.target.value as UserRole }))
                    }
                    className="w-full bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-sm text-vault-text focus:outline-none focus:ring-1 focus:ring-vault-accent"
                  >
                    <option value="admin">{t('admin.users.roleAdmin')}</option>
                    <option value="member">{t('admin.users.roleMember')}</option>
                    <option value="viewer">{t('admin.users.roleViewer')}</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-vault-text">
                    {t('admin.users.email')}
                    <span className="ml-1 text-vault-text-secondary font-normal text-xs">
                      ({t('common.optional')})
                    </span>
                  </label>
                  <input
                    type="email"
                    value={createForm.email}
                    onChange={(e) => setCreateForm((f) => ({ ...f, email: e.target.value }))}
                    className="w-full bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-sm text-vault-text placeholder-vault-text-secondary focus:outline-none focus:ring-1 focus:ring-vault-accent"
                    placeholder={t('admin.users.email')}
                    autoComplete="off"
                  />
                </div>
          </form>
        </Dialog>

        {/* Delete Confirmation Dialog */}
        <AlertDialog
          open={deleteOpen}
          onOpenChange={(o) => {
            if (!o) setDeleteOpen(false)
          }}
          title={t('admin.users.deleteTitle')}
          description={
            <>
              <span className="block">{t('admin.users.deleteConfirm')}</span>
              <span className="mt-2 block font-medium text-vault-text">{deleteTarget?.username}</span>
            </>
          }
          confirmLabel={t('admin.users.delete')}
          onConfirm={handleDelete}
          destructive
          busy={deleting}
        />
      </main>
    </PageContainer>
  )
}
