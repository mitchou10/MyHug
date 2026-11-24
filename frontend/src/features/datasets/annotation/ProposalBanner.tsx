import { Check, Sparkles, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Proposal } from './store'

/** Says that what is on screen was proposed by a model: nothing counts until a human validates it. */
export function ProposalBanner({ proposal, edited, onAccept, onReject }: { proposal: Proposal; edited: boolean; onAccept: () => void; onReject: () => void }) {
  const { t } = useTranslation()
  return (
    <div role="status" className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
      <Sparkles className="size-4 shrink-0 text-amber-600" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{t('datasets.annotation.pre.title', { model: proposal.model })}</span>
          <Badge variant="outline">{t('datasets.annotation.pre.confidence', { n: Math.round(proposal.confidence * 100) })}</Badge>
          {edited && <Badge variant="secondary">{t('datasets.annotation.pre.edited')}</Badge>}
        </div>
        <p className="text-xs text-muted-foreground">{t('datasets.annotation.pre.hint')}</p>
      </div>
      <div className="flex gap-1.5">
        <Button size="sm" variant="outline" onClick={onReject}><X />{t('datasets.annotation.pre.reject')}</Button>
        <Button size="sm" onClick={onAccept}><Check />{t(edited ? 'datasets.annotation.pre.acceptEdited' : 'datasets.annotation.pre.accept')}</Button>
      </div>
    </div>
  )
}
