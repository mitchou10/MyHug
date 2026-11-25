import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useMembers, useRemoveMember, useSetMember } from '../api/models'
import type { Member, Model } from '../types'

const ROLES: Member['role'][] = ['reader', 'maintainer']

/** Who has access to a model besides its creator: for the people who can edit it (the API says no to anybody else). */
export function MembersDialog({ model, open, onOpenChange }: { model: Model; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const members = useMembers(model, open)
  const set = useSetMember(model)
  const remove = useRemoveMember(model)
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<Member['role']>('reader')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('models.members.title')}</DialogTitle>
          <DialogDescription>{t('models.members.hint')}</DialogDescription>
        </DialogHeader>
        <ul className="divide-y rounded-lg border">
          {members.data?.map((m) => (
            <li key={m.userId} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="flex-1 break-all">{m.userId}</span>
              <select className="h-8 rounded-md border bg-background px-2 text-xs" value={m.role} aria-label={t('models.members.role', { user: m.userId })}
                onChange={(e) => set.mutate({ userId: m.userId, role: e.target.value as Member['role'] })}>
                {ROLES.map((r) => <option key={r} value={r}>{t(`models.members.roles.${r}`)}</option>)}
              </select>
              <Button size="icon" variant="ghost" aria-label={t('models.members.remove', { user: m.userId })} onClick={() => remove.mutate(m.userId)}><Trash2 /></Button>
            </li>
          ))}
          {members.data && !members.data.length && <li className="px-3 py-3 text-sm text-muted-foreground">{t('models.members.none')}</li>}
        </ul>
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); set.mutate({ userId: userId.trim(), role }, { onSuccess: () => setUserId('') }) }}>
          <Input className="min-w-40 flex-1" aria-label={t('models.members.user')} placeholder={t('models.members.user')} value={userId} onChange={(e) => setUserId(e.target.value)} />
          <select className="h-9 rounded-md border bg-background px-2 text-sm" value={role} aria-label={t('models.members.newRole')} onChange={(e) => setRole(e.target.value as Member['role'])}>
            {ROLES.map((r) => <option key={r} value={r}>{t(`models.members.roles.${r}`)}</option>)}
          </select>
          <Button type="submit" disabled={!userId.trim() || set.isPending}>{t('models.members.add')}</Button>
        </form>
        <ErrorNotice error={members.error ?? set.error ?? remove.error} />
      </DialogContent>
    </Dialog>
  )
}
