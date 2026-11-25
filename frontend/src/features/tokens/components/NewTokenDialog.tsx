import { Check, Copy, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { useCreateToken } from '../api/tokens'
import type { CreatedToken, Scope } from '../types'

const EXPIRIES: (number | null)[] = [30, 90, 365, null]

/**
 * Makes a token, and shows it once. The secret is only in this dialog's state: when it closes, it is gone, and the
 * page can only list the first characters.
 */
export function NewTokenDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation()
  const create = useCreateToken()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<Scope>('read')
  const [days, setDays] = useState<number | null>(90)
  const [created, setCreated] = useState<CreatedToken | null>(null)
  const [copied, setCopied] = useState(false)

  const close = (next: boolean) => {
    if (next) return onOpenChange(true)
    setCreated(null) // the secret is let go
    setName('')
    setScope('read')
    setDays(90)
    setCopied(false)
    create.reset()
    onOpenChange(false)
  }
  const submit = () => create.mutate({ name: name.trim(), scope, expiresInDays: days }, { onSuccess: setCreated })
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created!.secret)
      setCopied(true)
    } catch {
      setCopied(false) // the token is on screen: it can still be selected by hand
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>{t('tokens.created.title')}</DialogTitle>
              <DialogDescription>{t('tokens.created.hint')}</DialogDescription>
            </DialogHeader>
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              {t('tokens.created.warning')}
            </div>
            <div className="flex items-center gap-2">
              <Input readOnly aria-label={t('tokens.created.token')} value={created.secret} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
              <Button variant="outline" onClick={copy}>
                {copied ? <Check /> : <Copy />}
                {t(copied ? 'tokens.created.copied' : 'tokens.created.copy')}
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={() => close(false)}>{t('tokens.created.done')}</Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>{t('tokens.new')}</DialogTitle>
              <DialogDescription>{t('tokens.newHint')}</DialogDescription>
            </DialogHeader>
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) submit() }}>
              <div className="space-y-1.5">
                <Label htmlFor="token-name">{t('tokens.fields.name')}</Label>
                <Input id="token-name" autoFocus maxLength={100} placeholder={t('tokens.fields.namePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <fieldset className="space-y-1.5">
                <legend className="text-sm font-medium">{t('tokens.fields.scope')}</legend>
                {(['read', 'write'] as const).map((s) => (
                  <label key={s} className={cn('flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm', scope === s && 'border-primary bg-muted/50')}>
                    <input type="radio" name="scope" className="mt-0.5 accent-primary" checked={scope === s} onChange={() => setScope(s)} />
                    <span>
                      <span className="font-medium">{t(`tokens.scope.${s}`)}</span>
                      <span className="block text-xs text-muted-foreground">{t(`tokens.scopeHint.${s}`)}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
              <div className="space-y-1.5">
                <Label htmlFor="token-days">{t('tokens.fields.expires')}</Label>
                <select id="token-days" className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={days ?? ''} onChange={(e) => setDays(e.target.value ? Number(e.target.value) : null)}>
                  {EXPIRIES.map((d) => <option key={d ?? 'never'} value={d ?? ''}>{d ? t('tokens.expiry', { count: d }) : t('tokens.neverExpires')}</option>)}
                </select>
              </div>
              <p className="text-xs text-muted-foreground">{t('tokens.rights')}</p>
              <ErrorNotice error={create.error} />
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => close(false)}>{t('datasets.annotation.cancel')}</Button>
                <Button type="submit" disabled={!name.trim() || create.isPending}>{t('tokens.make')}</Button>
              </DialogFooter>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
