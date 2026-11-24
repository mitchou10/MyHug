import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { canSee, hasItem, useCollections, type ItemType } from '../store'

/** The collections a dataset or a model is in (the private ones of other people are not shown). */
export function InCollections({ type, reference }: { type: ItemType; reference: string }) {
  const { t } = useTranslation()
  const { collections } = useCollections()
  const list = collections.filter((c) => canSee(c) && hasItem(c, type, reference))
  if (!list.length) return null
  return (
    <div className="space-y-1.5 border-t pt-3">
      <h3 className="text-xs font-medium text-muted-foreground">{t('collections.title')}</h3>
      <ul className="space-y-1">{list.slice(0, 5).map((c) => <li key={c.id}><Link className="underline-offset-2 hover:underline" to={`/collections/${c.owner}/${c.slug}`}>{c.title}</Link></li>)}</ul>
    </div>
  )
}
