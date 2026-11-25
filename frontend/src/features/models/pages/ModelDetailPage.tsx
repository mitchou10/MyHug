import { ArrowLeft, Download, ExternalLink, Heart, Plus, Sparkles, Trash2, Users } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { statsOf, useAnnotations } from '@/features/datasets/annotation/store'
import { formatCount } from '@/features/datasets/format'
import { getDataset } from '@/features/datasets/mockData'
import { AddToCollection } from '@/features/collections/components/AddToCollection'
import { InCollections } from '@/features/collections/components/InCollections'
import { ApiError } from '@/lib/api'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { useDeleteModel, useLike, useModel } from '../api/models'
import { EvaluationsSection } from '../components/EvaluationsSection'
import { FilesTab } from '../components/FilesTab'
import { MembersDialog } from '../components/MembersDialog'
import { ModelWidget } from '../components/ModelWidget'
import { UploadDialog } from '../components/UploadDialog'
import { VersionsTab } from '../components/VersionsTab'
import { formatBytes } from '../format'
import type { Model } from '../types'

const pct = (x: number) => `${Math.round(x * 100)} %`

/** One model: its card, a place to try it (when it is served), its versions, how it performs, its files. */
export function ModelDetailPage() {
  const { owner, name } = useParams()
  const model = useModel(owner, name)
  if (model.isPending) return <Container className="max-w-6xl py-6"><Skeleton className="h-10 w-64" /></Container>
  // A model that is private and not mine answers 404, like one that does not exist: it is never "forbidden".
  if (model.error instanceof ApiError && (model.error.status === 404 || model.error.status === 403)) return <NotFoundPage />
  if (model.isError) return <Container className="max-w-6xl py-6"><ErrorNotice error={model.error} /></Container>
  return <Detail m={model.data} />
}

function Detail({ m }: { m: Model }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const { projects, runs, decisions } = useAnnotations()
  const like = useLike(m)
  const remove = useDeleteModel(m)
  const [uploading, setUploading] = useState(false)
  const [sharing, setSharing] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const mine = decisions.filter((d) => d.model === m.name)
  const st = statsOf(mine)
  const used = [...new Set(runs.filter((r) => r.model === m.name).map((r) => r.projectId))].map((id) => projects.find((p) => p.id === id)).filter((p) => !!p)
  // The tasks it could pre-annotate: its kind of task, on the kind of data it reads.
  const compatible = projects.filter((p) => m.tasks.includes(p.task) && m.inputs.includes(getDataset(...(p.datasetKey.split('/') as [string, string]))?.modality ?? 'text'))

  const meta: [string, string][] = [
    [t('models.meta.reads'), m.inputs.map((i) => t(`datasets.modalities.${i}`)).join(', ')],
    [t('models.meta.languages'), m.languages.join(', ') || '—'],
    [t('models.meta.license'), m.license || '—'],
    [t('models.meta.library'), m.library || '—'],
    [t('models.meta.params'), m.parameters ? formatCount(m.parameters) : '—'],
    [t('models.meta.size'), m.sizeBytes ? formatBytes(m.sizeBytes) : '—'],
    [t('models.meta.version'), m.version ? `v${m.version}` : '—'],
    [t('models.meta.updated'), new Date(m.updatedAt).toLocaleDateString(i18n.language)],
  ]

  return (
    <Container className="max-w-6xl py-6">
      <Link to="/models" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{t('models.back')}</Link>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold break-all">{m.address}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {m.tasks.map((k) => <Badge key={k} variant="secondary">{t(`datasets.annotation.tasks.${k}.title`)}</Badge>)}
            {m.tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>)}
            {m.visibility === 'private' && <Badge variant="outline">{t('models.private')}</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <AddToCollection type="model" reference={m.address} />
          <Button variant={m.liked ? 'default' : 'outline'} aria-pressed={m.liked} disabled={like.isPending} onClick={() => like.mutate(!m.liked)}><Heart />{formatCount(m.likes)}</Button>
          <Button variant="outline" disabled title={t('models.downloads')}><Download />{formatCount(m.downloads)}</Button>
          {/* Only the people who can edit the model are given the address: nothing is rendered for the others. */}
          {m.mlflowUrl && (
            <a href={m.mlflowUrl} target="_blank" rel="noopener noreferrer" className={buttonVariants({ variant: 'outline' })}>
              <ExternalLink />{t('models.openMlflow')}
            </a>
          )}
        </div>
      </div>
      {m.canEdit && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setUploading(true)}><Plus />{t('models.newVersion')}</Button>
          <Button size="sm" variant="outline" onClick={() => setSharing(true)}><Users />{t('models.members.title')}</Button>
          {confirming
            ? <Button size="sm" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(undefined, { onSuccess: () => void navigate('/models') })}>{t('models.confirmDelete')}</Button>
            : <Button size="sm" variant="ghost" onClick={() => setConfirming(true)} onBlur={() => setConfirming(false)}><Trash2 />{t('models.delete')}</Button>}
          <ErrorNotice error={remove.error ?? like.error} />
        </div>
      )}

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_16rem]">
        <Tabs defaultValue="card">
          <TabsList>
            <TabsTrigger value="card">{t('models.tabs.card')}</TabsTrigger>
            {m.serving && <TabsTrigger value="try">{t('models.tabs.try')}</TabsTrigger>}
            <TabsTrigger value="eval">{t('models.tabs.eval')}</TabsTrigger>
            <TabsTrigger value="versions">{t('models.tabs.versions')}</TabsTrigger>
            <TabsTrigger value="files">{t('models.tabs.files')}</TabsTrigger>
          </TabsList>

          <TabsContent value="card" className="mt-4 space-y-5">
            <p>{m.description || t('models.noDescription')}</p>
            {m.card && <div className="rounded-lg border p-3 text-sm whitespace-pre-wrap">{m.card}</div>}
            <section className="space-y-2">
              <h2 className="text-sm font-medium">{t('models.card.does')}</h2>
              <ul className="space-y-1.5">
                {m.tasks.map((k) => <li key={k} className="rounded-md border p-2.5 text-sm"><span className="font-medium">{t(`datasets.annotation.tasks.${k}.title`)}</span><span className="block text-xs text-muted-foreground">{t(`datasets.annotation.tasks.${k}.hint`)}</span></li>)}
                {!m.tasks.length && <li className="text-sm text-muted-foreground">{t('models.noTask')}</li>}
              </ul>
            </section>
            <section className="space-y-2">
              <h2 className="text-sm font-medium">{t('models.card.trainedOn')}</h2>
              {m.trainedOn.length ? <ul className="flex flex-wrap gap-1.5">{m.trainedOn.map((k) => <li key={k}><Link className="rounded-full border px-2.5 py-1 text-xs hover:bg-muted" to={`/datasets/${k}`}>{k}</Link></li>)}</ul> : <p className="text-sm text-muted-foreground">{t('models.card.unknownData')}</p>}
            </section>
            {m.codeUrl && (
              <section className="space-y-2">
                <h2 className="text-sm font-medium">{t('models.card.code')}</h2>
                <a href={m.codeUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm break-all underline-offset-2 hover:underline">{m.codeUrl}<ExternalLink className="size-3" /></a>
              </section>
            )}
            <section className="space-y-2">
              <h2 className="text-sm font-medium">{t('models.card.limits')}</h2>
              <p className="text-sm text-muted-foreground">{t('models.card.limitsText')}</p>
            </section>
            {m.serving && (
              <section className="space-y-2">
                <h2 className="text-sm font-medium">{t('models.card.usage')}</h2>
                <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">{`POST /api/models/${m.address}/predict\n{ "input": … }`}</pre>
              </section>
            )}
          </TabsContent>

          {m.serving && <TabsContent value="try" className="mt-4"><ModelWidget key={m.id} model={m} serving={m.serving} /></TabsContent>}

          <TabsContent value="eval" className="mt-4 space-y-6">
            <EvaluationsSection model={m} />

            <section className="space-y-2">
              <h2 className="flex items-center gap-1.5 text-sm font-medium"><Sparkles className="size-4 text-amber-600" />{t('models.eval.byHumans')}</h2>
              {st.decided ? (
                <>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline">{t('models.eval.decisions', { n: st.decided })}</Badge>
                    <Badge variant="outline">{t('datasets.annotation.pre.counts.accepted', { n: st.accepted })}</Badge>
                    <Badge variant="outline">{t('datasets.annotation.pre.counts.edited', { n: st.edited })}</Badge>
                    <Badge variant="outline">{t('datasets.annotation.pre.counts.rejected', { n: st.rejected })}</Badge>
                    <Badge>{t('models.eval.score', { score: pct(st.score) })}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{t('models.eval.byHumansHint')}</p>
                </>
              ) : <p className="text-sm text-muted-foreground">{t('models.eval.noDecisions')}</p>}
              {used.length > 0 && <p className="text-sm">{t('models.eval.usedOn')} {used.map((p, i) => <span key={p!.id}>{i > 0 && ', '}<Link className="underline-offset-2 hover:underline" to={`/datasets/${p!.datasetKey}`}>{p!.datasetKey} · {p!.name}</Link></span>)}</p>}
            </section>

            <section className="space-y-2">
              <h2 className="text-sm font-medium">{t('models.eval.compatible')}</h2>
              {compatible.length ? <ul className="space-y-1">{compatible.map((p) => <li key={p.id} className="text-sm"><Link className="underline-offset-2 hover:underline" to={`/datasets/${p.datasetKey}`}>{p.datasetKey}</Link> · {p.name}</li>)}</ul> : <p className="text-sm text-muted-foreground">{t('models.eval.noCompatible')}</p>}
            </section>
          </TabsContent>

          <TabsContent value="versions" className="mt-4"><VersionsTab model={m} /></TabsContent>
          <TabsContent value="files" className="mt-4"><FilesTab model={m} /></TabsContent>
        </Tabs>

        <aside className="h-fit space-y-2 rounded-lg border p-4 text-sm">
          {meta.map(([k, v]) => <div key={k} className="flex justify-between gap-2"><span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{v}</span></div>)}
          <InCollections type="model" reference={m.address} />
        </aside>
      </div>
      {uploading && <UploadDialog model={m} open onOpenChange={(o) => !o && setUploading(false)} />}
      {sharing && <MembersDialog model={m} open onOpenChange={(o) => !o && setSharing(false)} />}
    </Container>
  )
}
