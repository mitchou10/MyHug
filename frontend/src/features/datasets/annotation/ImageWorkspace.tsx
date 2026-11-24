import { ArrowLeft, Check, MousePointer2, Pentagon, Plus, RectangleHorizontal, SkipForward, Spline, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { SceneGraphics } from '../components/viewers/SceneGraphics'
import type { Dataset } from '../mockData'
import { KeypointsEditor } from './KeypointsEditor'
import { PolygonCanvas, type Tool } from './PolygonCanvas'
import { labelsOf, newPair, useAnnotations, withLabel, commitAnswer, rejectProposal, type Answer, type Proposal, type AnnotationProject, type ImageObject, type Pt, withOrigin } from './store'
import { ProposalBanner } from './ProposalBanner'
import { color } from './ui'

const uid = () => Math.random().toString(36).slice(2, 8)

/** Where one annotates images, one at a time: polygons for detection and segmentation, a label, or sentences. */
export function ImageWorkspace({ dataset: d, project }: { dataset: Dataset; project: AnnotationProject }) {
  const { t } = useTranslation()
  const store = useAnnotations()
  const saved = store.answers[project.id]
  const proposed = store.proposals[project.id]
  const task = project.task
  const polygons = task === 'image_detection' || task === 'image_segmentation' || task === 'image_polyline'
  const kind = task === 'image_segmentation' ? 'segmentation' : task === 'image_polyline' ? 'polyline' : 'detection'
  /** A polygon needs 3 points, a line 2. */
  const minPoints = kind === 'polyline' ? 2 : 3
  const rows = d.sample

  const [idx, setIdx] = useState(0)
  const [draft, setDraft] = useState<Answer>(() => saved?.[0] ?? {})
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [tool, setTool] = useState<Tool>('polygon')
  const [chosen, setChosen] = useState<string | null>(null)
  // The label used to draw: the one chosen, else the first of the task (a shape can never be left without a label).
  const active = project.labels.some((l) => l.id === chosen) ? chosen : (project.labels[0]?.id ?? null)
  const [selected, setSelected] = useState<string | null>(null)
  const [drawing, setDrawing] = useState<Pt[]>([])

  const [file, W, H] = [String(rows[idx][0]), Number(rows[idx][1]), Number(rows[idx][2])]
  const objects = draft.objects ?? []
  const labelName = (id: string) => project.labels.find((l) => l.id === id)?.name
  const doneCount = Object.keys(saved ?? {}).length

  /** What an item starts from: the answer already given, else the proposal of the model if the task has one. */
  const load = (i: number) => {
    const pr = saved?.[i] ? null : (proposed?.[i] ?? null)
    setProposal(pr)
    setDraft(saved?.[i] ?? pr?.answer ?? {})
  }
  useEffect(() => { load(0) }, [project.id])
  // A proposal can arrive while the item is on screen (the run is still going): take it if nothing was typed yet.
  useEffect(() => { if (!proposal && !saved?.[idx] && proposed?.[idx] && Object.keys(draft).length === 0) load(idx) }, [proposed?.[idx]])
  const go = (i: number) => { setIdx(i); load(i); setSelected(null); setDrawing([]) }
  const submit = () => {
    const clean: Answer = { ...draft, captions: draft.captions?.filter((c) => c.trim()) }
    if (task === 'image_vqa') clean.qa = pairs.filter((p) => p.question.trim() || p.answer.trim())
    commitAnswer(project.id, idx, clean, proposal)
    go(Math.min(rows.length - 1, idx + 1))
  }
  const setObjects = (objs: ImageObject[]) => setDraft({ ...draft, objects: objs })
  const finish = (points: Pt[]) => {
    if (!active || points.length < minPoints) return
    const o: ImageObject = { id: uid(), label: active, points }
    // Stay in the drawing tool, ready for the next shape.
    setObjects([...objects, o]); setSelected(null); setDrawing([])
  }
  const removeSelected = () => { if (selected) { setObjects(objects.filter((o) => o.id !== selected)); setSelected(null) } }
  /** Choosing a label sets the one used to draw, and relabels the selected shape if there is one. */
  const chooseLabel = (id: string) => {
    if (task === 'image_classification') return setDraft(withLabel(draft, id, project.multiLabel))
    setChosen(id)
    if (tool === 'select' && selected) setObjects(objects.map((o) => (o.id === selected ? { ...o, label: id } : o)))
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('textarea,input')) return
      if (task === 'image_keypoints') { if (e.key === 'Enter') submit(); return }
      const n = Number(e.key)
      if (n >= 1 && n <= project.labels.length) return chooseLabel(project.labels[n - 1].id)
      if (polygons) {
        if (e.key === 'v') setTool('select')
        else if (e.key === 'p') setTool('polygon')
        else if (e.key === 'r' && kind === 'detection') setTool('rect')
        else if (e.key === 'Escape') { setDrawing([]); setSelected(null) }
        else if (e.key === 'Backspace' && drawing.length) setDrawing(drawing.slice(0, -1))
        else if ((e.key === 'Delete' || e.key === 'Backspace') && !drawing.length) removeSelected()
        else if (e.key === 'Enter') { if (drawing.length >= minPoints) finish(drawing); else submit() }
      } else if (e.key === 'Enter' && task !== 'image_caption') submit()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const labelButtons = (selectedIds: string[]) => (
    <div className="grid gap-1.5">
      {project.labels.map((l, i) => {
        const on = selectedIds.includes(l.id)
        return (
          <Button key={l.id} variant="outline" title={l.description} onClick={() => chooseLabel(l.id)} className={cn('h-auto justify-start gap-2 py-1.5 text-left whitespace-normal', on && 'ring-2 ring-primary')} style={on ? color(l.id) : undefined}>
            <kbd className="rounded bg-background/70 px-1.5 text-xs">{i + 1}</kbd>
            <span className="size-2.5 shrink-0 rounded-full" style={color(l.id)} />
            <span className="flex flex-col"><span>{l.name}</span>{l.description && <span className="text-xs font-normal opacity-80">{l.description}</span>}</span>
          </Button>
        )
      })}
    </div>
  )

  const tools: [Tool, string, typeof Pentagon][] = [['select', 'v', MousePointer2], ['polygon', 'p', kind === 'polyline' ? Spline : Pentagon], ...(kind === 'detection' ? [['rect', 'r', RectangleHorizontal] as [Tool, string, typeof Pentagon]] : [])]
  const captions = draft.captions?.length ? draft.captions : ['']
  const [blank] = useState(newPair)
  const pairs = draft.qa?.length ? draft.qa : [blank]
  const patchPair = (id: string, p: Partial<(typeof pairs)[number]>) => setDraft({ ...draft, qa: pairs.map((x) => (x.id === id ? { ...x, ...p } : x)) })

  const footer = (
    <div className="flex items-center justify-between border-t pt-3">
            <Button variant="ghost" onClick={() => go(Math.min(rows.length - 1, idx + 1))}><SkipForward />{t('datasets.annotation.skip')}</Button>
            <Button onClick={submit}><Check />{t('datasets.annotation.submit')}</Button>
          </div>
  )

  return (
    <Container className="max-w-7xl py-6">
      <Link to={`/datasets/${d.owner}/${d.name}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{d.owner}/{d.name}</Link>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <Badge variant="secondary">{t(`datasets.annotation.tasks.${task}.title`)}</Badge>
        <span className="ml-auto text-sm text-muted-foreground">{t('datasets.annotation.progress', { done: doneCount, total: rows.length })}</span>
      </div>
      <div className="mt-2 flex gap-1">
        {rows.map((_, i) => <button key={i} aria-label={`#${i}`} onClick={() => go(i)} className={cn('h-1.5 flex-1 rounded-full', saved?.[i] ? 'bg-primary' : 'bg-muted', i === idx && 'ring-2 ring-ring ring-offset-1')} />)}
      </div>

      {proposal && <ProposalBanner proposal={proposal} edited={withOrigin(draft, proposal).origin === 'model_edited'} onAccept={submit} onReject={() => { rejectProposal(project.id, idx, proposal); setProposal(null); setDraft({}) }} />}

      {task === 'image_keypoints' ? (
        <KeypointsEditor file={file} W={W} H={H} project={project} draft={draft} setDraft={setDraft} footer={footer} />
      ) : (
      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-2">
          {polygons ? (
            <>
              <PolygonCanvas file={file} width={W} height={H} objects={objects} drawing={drawing} setDrawing={setDrawing} tool={tool} selectedId={selected} onSelect={setSelected} onChange={setObjects} onFinish={finish} kind={kind} labelName={labelName} />
              <p className="text-xs text-muted-foreground">
                {tool === 'select' ? t('datasets.annotation.image.hintSelect') : t(kind === 'segmentation' ? 'datasets.annotation.image.hintSegment' : kind === 'polyline' ? 'datasets.annotation.image.hintPolyline' : 'datasets.annotation.image.hintDetect')}
                {drawing.length > 0 && ` · ${t('datasets.annotation.image.drawing', { n: drawing.length })}`}
              </p>
            </>
          ) : (
            <svg viewBox={`0 0 ${W} ${H}`} className="block w-full rounded-lg border" role="img" aria-label={file}><SceneGraphics file={file} width={W} height={H} /></svg>
          )}
          <p className="text-xs text-muted-foreground">{file} · {W}×{H} · {t('datasets.annotation.image.emptyScene')}</p>
        </div>

        <aside className="space-y-4 rounded-lg border p-4 lg:sticky lg:top-4">
          {polygons && (
            <>
              <div className={cn('grid gap-1.5', tools.length === 3 ? 'grid-cols-3' : 'grid-cols-2')} role="group">
                {tools.map(([k, key, Icon]) => (
                  <Button key={k} variant={tool === k ? 'default' : 'outline'} aria-pressed={tool === k} title={`${t(`datasets.annotation.image.tools.${k}`)} (${key.toUpperCase()})`}
                    className="h-auto flex-col gap-1 px-1 py-2 text-xs" onClick={() => { setTool(k); setDrawing([]) }}>
                    <Icon className="size-5" />
                    <span>{t(`datasets.annotation.image.tools.${k === 'polygon' && kind === 'polyline' ? 'line' : k}`)}</span>
                  </Button>
                ))}
              </div>
              {labelButtons([tool === 'select' && selected ? objects.find((o) => o.id === selected)?.label : active].filter((x): x is string => !!x))}
              {drawing.length >= minPoints && <Button size="sm" className="w-full" onClick={() => finish(drawing)}>{t('datasets.annotation.image.finish')} <kbd className="rounded bg-primary-foreground/20 px-1.5 text-xs">↵</kbd></Button>}

              <div className="space-y-1.5">
                <h3 className="text-sm font-medium">{t(kind === 'segmentation' ? 'datasets.annotation.image.regions' : kind === 'polyline' ? 'datasets.annotation.image.lines' : 'datasets.annotation.image.objects')} · {objects.length}</h3>
                {!objects.length && <p className="text-xs text-muted-foreground">{t('datasets.annotation.image.none')}</p>}
                <ul className="max-h-72 space-y-1.5 overflow-y-auto">
                  {objects.map((o) => (
                    <li key={o.id} onClick={() => { setSelected(o.id); setTool('select') }} className={cn('space-y-1 rounded-md border p-2 text-sm', o.id === selected && 'ring-2 ring-primary')}>
                      <div className="flex items-center gap-2">
                        <span className="rounded-full border px-2 py-0.5 text-xs font-medium" style={color(o.label)}>{labelName(o.label) ?? t('datasets.annotation.deletedLabel')}</span>
                        <span className="text-xs text-muted-foreground">{t('datasets.annotation.image.points', { n: o.points.length })}</span>
                        <button className="ml-auto" aria-label="remove" onClick={(e) => { e.stopPropagation(); setObjects(objects.filter((x) => x.id !== o.id)); if (selected === o.id) setSelected(null) }}><Trash2 className="size-4" /></button>
                      </div>
                      {o.id === selected && <Input className="h-8" aria-label={t('datasets.annotation.spanReason')} placeholder={t('datasets.annotation.spanReason')} value={o.reason ?? ''} onChange={(e) => setObjects(objects.map((x) => (x.id === o.id ? { ...x, reason: e.target.value } : x)))} />}
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}

          {task === 'image_classification' && (
            <>
              {labelButtons(labelsOf(draft))}
              <div className="space-y-1.5">
                <label htmlFor="reason" className="text-sm font-medium">{t('datasets.annotation.reason')} <span className="font-normal text-muted-foreground">({t('datasets.annotation.optional')})</span></label>
                <Textarea id="reason" rows={2} placeholder={t('datasets.annotation.reasonPlaceholder')} value={draft.reason ?? ''} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
              </div>
            </>
          )}

          {task === 'image_caption' && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium">{t('datasets.annotation.image.caption')}</h3>
              <p className="text-xs text-muted-foreground">{t('datasets.annotation.image.captionHint')}</p>
              {captions.map((c, i) => (
                <div key={i} className="flex gap-1.5">
                  <Textarea rows={3} aria-label={`${t('datasets.annotation.image.caption')} ${i + 1}`} placeholder={t('datasets.annotation.image.captionPlaceholder')} value={c}
                    onChange={(e) => setDraft({ ...draft, captions: captions.map((x, j) => (j === i ? e.target.value : x)) })} />
                  {captions.length > 1 && <button aria-label={t('datasets.annotation.image.removeCaption')} onClick={() => setDraft({ ...draft, captions: captions.filter((_, j) => j !== i) })}><X className="size-4" /></button>}
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={() => setDraft({ ...draft, captions: [...captions, ''] })}><Plus />{t('datasets.annotation.image.addCaption')}</Button>
            </div>
          )}

          {task === 'image_vqa' && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">{t('datasets.annotation.image.vqa.hint')}</p>
              {pairs.map((p, n) => (
                <div key={p.id} className="space-y-1.5 rounded-lg border p-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full border px-2 py-0.5 text-xs font-medium" style={color(`qa${n}`)}>Q{n + 1}</span>
                    {pairs.length > 1 && <button className="ml-auto" aria-label="remove" onClick={() => setDraft({ ...draft, qa: pairs.filter((x) => x !== p) })}><X className="size-4" /></button>}
                  </div>
                  <Input aria-label={t('datasets.annotation.image.vqa.question')} placeholder={t('datasets.annotation.image.vqa.question')} value={p.question} onChange={(e) => patchPair(p.id, { question: e.target.value })} />
                  <Input aria-label={t('datasets.annotation.image.vqa.answer')} placeholder={t('datasets.annotation.image.vqa.answer')} value={p.answer} onChange={(e) => patchPair(p.id, { answer: e.target.value })} />
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={() => setDraft({ ...draft, qa: [...pairs, newPair()] })}><Plus />{t('datasets.annotation.image.vqa.add')}</Button>
            </div>
          )}

          {footer}
        </aside>
      </div>
      )}
    </Container>
  )
}
