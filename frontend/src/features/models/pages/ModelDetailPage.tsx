import { ArrowLeft, Download, FileText, Heart, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { statsOf, useAnnotations } from '@/features/datasets/annotation/store'
import { formatCount, formatSize } from '@/features/datasets/format'
import { getDataset } from '@/features/datasets/mockData'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ModelWidget } from '../components/ModelWidget'
import { describe } from '../describe'
import { findModel, toggleLike, useModels } from '../store'

const pct = (x: number) => `${Math.round(x * 100)} %`

/** One model: its card, a place to try it, its versions, how it performs, its files. */
export function ModelDetailPage() {
  const { t } = useTranslation()
  const { owner, name } = useParams()
  const { models, liked } = useModels()
  const { projects, runs, decisions } = useAnnotations()
  const m = findModel(models, owner, name)
  if (!m) return <NotFoundPage />

  const isLiked = liked.has(m.id)
  const mine = decisions.filter((d) => d.model === m.name)
  const st = statsOf(mine)
  const used = [...new Set(runs.filter((r) => r.model === m.name).map((r) => r.projectId))].map((id) => projects.find((p) => p.id === id)).filter((p) => !!p)
  // The tasks it could pre-annotate: its kind of task, on the kind of data it reads.
  const compatible = projects.filter((p) => m.tasks.includes(p.task) && m.inputs.includes(getDataset(...(p.datasetKey.split('/') as [string, string]))?.modality ?? 'text'))

  const meta: [string, string][] = [
    [t('models.meta.reads'), m.inputs.map((i) => t(`datasets.modalities.${i}`)).join(', ')],
    [t('models.meta.languages'), m.languages.join(', ') || '—'],
    [t('models.meta.license'), m.license],
    [t('models.meta.params'), m.paramsM ? `${m.paramsM} M` : '—'],
    [t('models.meta.size'), m.sizeMb ? formatSize(m.sizeMb) : '—'],
    [t('models.meta.version'), `v${m.version}`],
    [t('models.meta.updated'), m.updatedAt],
  ]

  return (
    <Container className="max-w-6xl py-6">
      <Link to="/models" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{t('models.back')}</Link>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold break-all">{m.owner}/{m.name}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {m.tasks.map((k) => <Badge key={k} variant="secondary">{t(`datasets.annotation.tasks.${k}.title`)}</Badge>)}
            {m.tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>)}
            {m.visibility === 'private' && <Badge variant="outline">{t('models.private')}</Badge>}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant={isLiked ? 'default' : 'outline'} aria-pressed={isLiked} onClick={() => toggleLike(m.id)}><Heart />{formatCount(m.likes + (isLiked ? 1 : 0))}</Button>
          <Button variant="outline" disabled><Download />{formatCount(m.downloads)}</Button>
        </div>
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_16rem]">
        <Tabs defaultValue="card">
          <TabsList>
            <TabsTrigger value="card">{t('models.tabs.card')}</TabsTrigger>
            <TabsTrigger value="try">{t('models.tabs.try')}</TabsTrigger>
            <TabsTrigger value="eval">{t('models.tabs.eval')}</TabsTrigger>
            <TabsTrigger value="versions">{t('models.tabs.versions')}</TabsTrigger>
            <TabsTrigger value="files">{t('models.tabs.files')}</TabsTrigger>
          </TabsList>

          <TabsContent value="card" className="mt-4 space-y-5">
            <p>{describe(m, t) || t('models.noDescription')}</p>
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
            <section className="space-y-2">
              <h2 className="text-sm font-medium">{t('models.card.limits')}</h2>
              <p className="text-sm text-muted-foreground">{t('models.card.limitsText')}</p>
            </section>
            <section className="space-y-2">
              <h2 className="text-sm font-medium">{t('models.card.usage')}</h2>
              <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">{`POST /api/models/${m.owner}/${m.name}/predict\n{ "items": [ { "ref": "…" } ] }`}</pre>
            </section>
          </TabsContent>

          <TabsContent value="try" className="mt-4"><ModelWidget key={m.id} model={m} /></TabsContent>

          <TabsContent value="eval" className="mt-4 space-y-6">
            <section className="space-y-2">
              <h2 className="text-sm font-medium">{t('models.eval.benchmarks')}</h2>
              {m.benchmarks.length ? (
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50 text-left text-xs"><tr><th className="px-3 py-2 font-medium">{t('models.eval.dataset')}</th><th className="px-3 py-2 font-medium">{t('models.eval.split')}</th><th className="px-3 py-2 font-medium">{t('models.eval.metric')}</th><th className="px-3 py-2 font-medium">{t('models.eval.value')}</th></tr></thead>
                    <tbody>{m.benchmarks.map((b) => (
                      <tr key={b.dataset + b.metric} className="border-t"><td className="px-3 py-2"><Link className="underline-offset-2 hover:underline" to={`/datasets/${b.dataset}`}>{b.dataset}</Link></td><td className="px-3 py-2">{b.split}</td><td className="px-3 py-2">{b.metric}{!b.higherIsBetter && ' ↓'}</td><td className="px-3 py-2 font-mono">{b.value}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : <p className="text-sm text-muted-foreground">{t('models.eval.none')}</p>}
            </section>

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

          <TabsContent value="versions" className="mt-4 divide-y rounded-lg border">
            {[...m.versions].reverse().map((v) => (
              <div key={v.version} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <span className="font-mono font-medium">v{v.version}</span>
                {v.version === m.version && <Badge>{t('models.versions.current')}</Badge>}
                <span className="flex-1 text-muted-foreground">{t(`models.versions.changelog.${v.changelog}`)}</span>
                <span className="text-xs text-muted-foreground">{v.sizeMb ? formatSize(v.sizeMb) : ''} · {v.date}</span>
              </div>
            ))}
          </TabsContent>

          <TabsContent value="files" className="mt-4 divide-y rounded-lg border">
            {m.files.map((f) => (
              <div key={f.path} className="flex items-center gap-2 px-4 py-2.5 text-sm">
                <FileText className="size-4 text-muted-foreground" />
                <span className="flex-1 break-all">{f.path}</span>
                <span className="text-muted-foreground">{formatSize(f.sizeMb)}</span>
              </div>
            ))}
          </TabsContent>
        </Tabs>

        <aside className="h-fit space-y-2 rounded-lg border p-4 text-sm">
          {meta.map(([k, v]) => <div key={k} className="flex justify-between gap-2"><span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{v}</span></div>)}
        </aside>
      </div>
    </Container>
  )
}
