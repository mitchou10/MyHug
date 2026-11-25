import { KeyRound, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Container } from '@/components/Container'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useRevokeToken, useTokens } from '../api/tokens'
import { NewTokenDialog } from '../components/NewTokenDialog'
import { stateOf, type AccessToken } from '../types'

/** The keys that let a program act as me. A token is shown once, when it is made: here there is only what identifies it. */
export function TokensPage() {
  const { t, i18n } = useTranslation()
  const tokens = useTokens()
  const revoke = useRevokeToken()
  const [creating, setCreating] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)
  const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(i18n.language) : null)

  const row = (token: AccessToken) => {
    const state = stateOf(token)
    return (
      <tr key={token.id} className="border-t">
        <td className="px-3 py-2 font-medium">{token.name}</td>
        <td className="px-3 py-2"><Badge variant={token.scope === 'write' ? 'default' : 'secondary'}>{t(`tokens.scope.${token.scope}`)}</Badge></td>
        <td className="px-3 py-2 font-mono text-xs">{token.prefix}…</td>
        <td className="px-3 py-2 text-muted-foreground">{day(token.createdAt)}</td>
        <td className="px-3 py-2 text-muted-foreground">{day(token.lastUsedAt) ?? t('tokens.never')}</td>
        <td className="px-3 py-2 text-muted-foreground">{day(token.expiresAt) ?? '—'}</td>
        <td className="px-3 py-2"><Badge variant={state === 'active' ? 'outline' : 'destructive'}>{t(`tokens.state.${state}`)}</Badge></td>
        <td className="px-3 py-2 text-right">
          {state === 'active' && (confirming === token.id
            ? <Button size="sm" variant="destructive" disabled={revoke.isPending} onClick={() => revoke.mutate(token.id, { onSettled: () => setConfirming(null) })}>{t('tokens.confirmRevoke')}</Button>
            : <Button size="icon" variant="ghost" aria-label={t('tokens.revoke', { name: token.name })} onClick={() => setConfirming(token.id)} onBlur={() => setConfirming(null)}><Trash2 /></Button>)}
        </td>
      </tr>
    )
  }

  return (
    <Container className="max-w-5xl py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><KeyRound className="size-6" aria-hidden />{t('tokens.title')}</h1>
          <p className="mt-1 max-w-2xl text-muted-foreground">{t('tokens.description')}</p>
        </div>
        <Button onClick={() => setCreating(true)}><Plus />{t('tokens.new')}</Button>
      </div>

      <ErrorNotice error={revoke.error} />
      {tokens.isPending && <p className="py-8 text-center text-sm text-muted-foreground">{t('tokens.loading')}</p>}
      {tokens.isError && <ErrorNotice error={tokens.error} />}
      {tokens.data && !tokens.data.length && (
        <p className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">{t('tokens.none')}</p>
      )}
      {tokens.data && tokens.data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs">
              <tr>
                {['name', 'scope', 'prefix', 'created', 'lastUsed', 'expires', 'state'].map((c) => <th key={c} className="px-3 py-2 font-medium">{t(`tokens.columns.${c}`)}</th>)}
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>{tokens.data.map(row)}</tbody>
          </table>
        </div>
      )}
      <NewTokenDialog open={creating} onOpenChange={setCreating} />
    </Container>
  )
}
