import { Pencil, Plus, Users } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCount } from '../format'
import type { Dataset } from '../mockData'
import { EditLabelsDialog } from './EditLabelsDialog'
import { NewProjectDialog } from './NewProjectDialog'
import { CURRENT_USER, useAnnotations, type AnnotationProject } from './store'

/** The annotation tasks of a dataset: anyone who can see the dataset can annotate. */
export function AnnotationTab({ dataset: d }: { dataset: Dataset }) {
  const { t } = useTranslation()
  const key = `${d.owner}/${d.name}`
  const { projects, answers } = useAnnotations()
  const mine = projects.filter((p) => p.datasetKey === key)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<AnnotationProject | null>(null)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{t('datasets.annotation.intro')}</p>
        <Button size="sm" onClick={() => setOpen(true)}><Plus />{t('datasets.annotation.new')}</Button>
      </div>

      {mine.length === 0 && <p className="rounded-lg border border-dashed py-10 text-center text-muted-foreground">{t('datasets.annotation.empty')}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {mine.map((p) => {
          const total = p.total || d.rows
          const mineDone = Object.keys(answers[p.id] ?? {}).length
          const done = p.done + mineDone
          return (
            <Card key={p.id}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">{p.name}<Badge variant="secondary">{t(`datasets.annotation.tasks.${p.task}.title`)}</Badge></CardTitle>
                <CardDescription className="flex items-center gap-1"><Users className="size-3" />{t('datasets.annotation.by', { user: p.createdBy, count: p.annotators })}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${Math.min(100, (done / total) * 100)}%` }} /></div>
                  <p className="mt-1 text-xs text-muted-foreground">{formatCount(done)} / {formatCount(total)}</p>
                </div>
                {p.labels.length > 0 && <div className="flex flex-wrap gap-1">{p.labels.map((l) => <Badge key={l.id} variant={l.kind === 'semantic' ? 'secondary' : 'outline'} title={l.description}>{l.name}</Badge>)}</div>}
                <div className="flex gap-2">
                  <Button size="sm" className="flex-1" render={<Link to={`/datasets/${key}/annotate/${p.id}`} />}>{t('datasets.annotation.start')}</Button>
                  {p.createdBy === CURRENT_USER && p.task !== 'qa' && <Button size="sm" variant="outline" onClick={() => setEditing(p)}><Pencil />{t('datasets.annotation.editLabels')}</Button>}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
      {editing && <EditLabelsDialog key={editing.id} project={projects.find((x) => x.id === editing.id)!} open onOpenChange={(o) => !o && setEditing(null)} />}
      <NewProjectDialog datasetKey={key} open={open} onOpenChange={setOpen} />
    </div>
  )
}
