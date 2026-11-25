import { Box, Download, Heart } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCount } from '@/features/datasets/format'
import { mainTask } from '../describe'
import { formatBytes } from '../format'
import type { Model } from '../types'

export function ModelCard({ model: m }: { model: Model }) {
  const { t } = useTranslation()
  return (
    <Link to={`/models/${m.owner}/${m.name}`} className="block rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
      <Card className="h-full transition-colors hover:bg-muted/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 break-all">
            <Box className="size-4 shrink-0 text-muted-foreground" />
            {m.address}
          </CardTitle>
          <CardDescription className="line-clamp-2 min-h-8">{m.description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{mainTask(m, t)}</Badge>
            {m.inputs.map((i) => <Badge key={i} variant="outline">{t(`datasets.modalities.${i}`)}</Badge>)}
            {m.visibility === 'private' && <Badge variant="outline">{t('models.private')}</Badge>}
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span>{m.version ? `v${m.version}` : t('models.noVersion')}</span>
            {m.parameters ? <span>{formatCount(m.parameters)}</span> : null}
            {m.sizeBytes ? <span>{formatBytes(m.sizeBytes)}</span> : null}
            <span className="ml-auto flex items-center gap-1" title={t('models.downloads')}><Download className="size-3" />{formatCount(m.downloads)}</span>
            <span className="flex items-center gap-1" title={t('models.likes')}><Heart className="size-3" />{formatCount(m.likes)}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
