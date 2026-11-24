import { Database, Download, Heart } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCount, formatSize } from '../format'
import type { Dataset } from '../mockData'

export function DatasetCard({ dataset: d }: { dataset: Dataset }) {
  const { t } = useTranslation()
  return (
    <Link to={`/datasets/${d.owner}/${d.name}`} className="block rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
      <Card className="h-full transition-colors hover:bg-muted/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 break-all">
            <Database className="size-4 shrink-0 text-muted-foreground" />
            {d.owner}/{d.name}
          </CardTitle>
          <CardDescription className="line-clamp-2">{d.description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{t(`datasets.modalities.${d.modality}`)}</Badge>
            {d.tags.slice(0, 2).map((tag) => (
              <Badge key={tag} variant="outline">{tag}</Badge>
            ))}
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span>{formatCount(d.rows)} {t('datasets.rows')}</span>
            <span>{formatSize(d.sizeMb)}</span>
            <span className="ml-auto flex items-center gap-1"><Download className="size-3" />{formatCount(d.downloads)}</span>
            <span className="flex items-center gap-1"><Heart className="size-3" />{formatCount(d.likes)}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
