import { Box, Download, Heart } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCount, formatSize } from '@/features/datasets/format'
import { describe, mainTask } from '../describe'
import type { Model } from '../mockData'

export function ModelCard({ model: m }: { model: Model }) {
  const { t } = useTranslation()
  return (
    <Link to={`/models/${m.owner}/${m.name}`} className="block rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
      <Card className="h-full transition-colors hover:bg-muted/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 break-all">
            <Box className="size-4 shrink-0 text-muted-foreground" />
            {m.owner}/{m.name}
          </CardTitle>
          <CardDescription className="line-clamp-2 min-h-8">{describe(m, t)}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{mainTask(m, t)}</Badge>
            {m.inputs.map((i) => <Badge key={i} variant="outline">{t(`datasets.modalities.${i}`)}</Badge>)}
            {m.visibility === 'private' && <Badge variant="outline">{t('models.private')}</Badge>}
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span>v{m.version}</span>
            <span>{m.paramsM} M</span>
            <span>{formatSize(m.sizeMb)}</span>
            <span className="ml-auto flex items-center gap-1"><Download className="size-3" />{formatCount(m.downloads)}</span>
            <span className="flex items-center gap-1"><Heart className="size-3" />{formatCount(m.likes)}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
