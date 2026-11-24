import { ArrowLeft, Download, FileText, Heart } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { AnnotationTab } from '../annotation/AnnotationTab'
import { DatasetViewer } from '../components/DatasetViewer'
import { formatCount, formatSize } from '../format'
import { getDataset } from '../mockData'

/** One dataset: card (README), data preview, files. */
export function DatasetDetailPage() {
  const { t } = useTranslation()
  const { owner, name } = useParams()
  const d = getDataset(owner, name)
  if (!d) return <NotFoundPage />

  const meta: [string, string][] = [
    [t('datasets.meta.modality'), t(`datasets.modalities.${d.modality}`)],
    [t('datasets.meta.language'), d.language],
    [t('datasets.meta.license'), d.license],
    [t('datasets.meta.rows'), formatCount(d.rows)],
    [t('datasets.meta.size'), formatSize(d.sizeMb)],
    [t('datasets.meta.updated'), d.updatedAt],
  ]

  return (
    <Container className="max-w-6xl py-6">
      <Link to="/datasets" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" />{t('datasets.back')}
      </Link>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold break-all">{d.owner}/{d.name}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">{d.tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>)}</div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline"><Heart />{formatCount(d.likes)}</Button>
          <Button><Download />{t('datasets.download')}</Button>
        </div>
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_16rem]">
        <Tabs defaultValue="card">
          <TabsList>
            <TabsTrigger value="card">{t('datasets.tabs.card')}</TabsTrigger>
            <TabsTrigger value="preview">{t('datasets.tabs.preview')}</TabsTrigger>
            {d.modality === 'text' && <TabsTrigger value="annotation">{t('datasets.tabs.annotation')}</TabsTrigger>}
            <TabsTrigger value="files">{t('datasets.tabs.files')}</TabsTrigger>
          </TabsList>

          <TabsContent value="card" className="mt-4 space-y-3">
            <p>{d.description}</p>
            <pre className="rounded-lg bg-muted p-4 text-sm whitespace-pre-wrap">{d.card}</pre>
          </TabsContent>

          <TabsContent value="preview" className="mt-4">
            <DatasetViewer dataset={d} />
          </TabsContent>

          <TabsContent value="annotation" className="mt-4"><AnnotationTab dataset={d} /></TabsContent>

          <TabsContent value="files" className="mt-4 divide-y rounded-lg border">
            {d.files.map((f) => (
              <div key={f.path} className="flex items-center gap-2 px-4 py-2.5 text-sm">
                <FileText className="size-4 text-muted-foreground" />
                <span className="flex-1 break-all">{f.path}</span>
                <span className="text-muted-foreground">{formatSize(f.sizeMb)}</span>
              </div>
            ))}
          </TabsContent>
        </Tabs>

        <aside className="h-fit space-y-2 rounded-lg border p-4 text-sm">
          {meta.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2"><span className="text-muted-foreground">{k}</span><span className="font-medium">{v}</span></div>
          ))}
        </aside>
      </div>
    </Container>
  )
}
