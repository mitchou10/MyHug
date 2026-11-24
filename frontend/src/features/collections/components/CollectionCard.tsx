import { Database, Box, Heart, Library, Lock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCount } from '@/features/datasets/format'
import type { Collection } from '../store'

export function CollectionCard({ collection: c }: { collection: Collection }) {
  const { t } = useTranslation()
  const datasets = c.items.filter((i) => i.type === 'dataset').length
  const models = c.items.length - datasets
  return (
    <Link to={`/collections/${c.owner}/${c.slug}`} className="block rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
      <Card className="h-full transition-colors hover:bg-muted/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Library className="size-4 shrink-0 text-muted-foreground" /><span className="truncate">{c.title}</span>{c.visibility === 'private' && <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-label={t('models.private')} />}</CardTitle>
          <CardDescription className="line-clamp-2 min-h-8">{c.description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary"><Database />{t('collections.datasets', { count: datasets })}</Badge>
            <Badge variant="secondary"><Box />{t('collections.models', { count: models })}</Badge>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{c.owner}</span><span>{c.updatedAt}</span>
            <span className="ml-auto flex items-center gap-1"><Heart className="size-3" />{formatCount(c.likes)}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
