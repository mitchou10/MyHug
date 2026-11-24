import { ArrowLeft, Check, Flag, MousePointer2, Pause, Play, Plus, SkipForward, SquareDashedMousePointer, Trash2, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Container } from '@/components/Container'
import { hue } from '../components/viewers/seed'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { Dataset } from '../mockData'
import { fmtTime } from './audioMock'
import { ScaleInput } from './ScaleInput'
import type { Player } from './useAudioPlayer'
import { Waveform, type AudioTool } from './Waveform'
import { DEFAULT_TRACKS, labelsOf, useAnnotations, usesRegions, withLabel, commitAnswer, rejectProposal, type Answer, type Proposal, type AnnotationProject, type AudioSegment, withOrigin } from './store'
import { ProposalBanner } from './ProposalBanner'
import { color } from './ui'

const uid = () => Math.random().toString(36).slice(2, 8)
const SPEEDS = [0.5, 0.75, 1, 1.5, 2]
const regionLabels = (s: AudioSegment) => s.labels ?? (s.label ? [s.label] : [])

/** What a kind of media provides to the workspace: the player, what to draw on top of the timeline, and its extra controls. */
export interface Media {
  clip: { duration: number; peaks: number[]; line?: boolean; format?: (t: number) => string }; player: Player
  view?: ReactNode; extra?: ReactNode; video?: boolean
  /** Nothing to play (a series): no play button or speed, the cursor is moved by clicking. */
  still?: boolean
  /** How to write a moment (a date, for a series); seconds by default. */
  format?: (t: number) => string
  /** The step of the time fields: 0.1 s by default, one point for a series. */
  step?: number
}
export type UseMedia = (file: string, duration: number, dataset: Dataset) => Media

/**
 * Where one annotates a sound or a video, one clip at a time. Either the whole clip gets the answer (a label, a score, a
 * description), or stretches of it do: each stretch is a region on a track, and carries what the task asks for
 * (labels, a text, a score). Several tracks let regions overlap, e.g. two speakers.
 */
export function TimedWorkspace({ dataset: d, project, useMedia }: { dataset: Dataset; project: AnnotationProject; useMedia: UseMedia }) {
  const { t } = useTranslation()
  const store = useAnnotations()
  const saved = store.answers[project.id]
  const proposed = store.proposals[project.id]
  const task = project.task
  const regionsMode = usesRegions(project)
  const tracks = project.tracks?.length ? project.tracks : DEFAULT_TRACKS
  // Sounds and videos: the rows of the table. Series: the list of series of the dataset.
  const rows = d.modality === 'timeseries' ? (d.collection ?? []).map((c) => ({ id: c.id, duration: c.points - 1 })) : d.sample.map((r) => ({ id: String(r[0]), duration: Number(r[2]) }))

  const [idx, setIdx] = useState(0)
  const [draft, setDraft] = useState<Answer>(() => saved?.[0] ?? {})
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [tool, setTool] = useState<AudioTool>('region')
  const [chosen, setChosen] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [activeTrack, setActiveTrack] = useState(0)
  const [markStart, setMarkStart] = useState<number | null>(null)
  const [zoom, setZoom] = useState(1)

  const [file, duration] = [rows[idx].id, rows[idx].duration]
  const { clip, player, view, extra, video, still, format, step } = useMedia(file, duration, d)
  const fmt = format ?? fmtTime
  const kind = task.replace(/^(audio|video|timeseries)_/, '')
  const segments = [...(draft.segments ?? [])].sort((a, b) => a.start - b.start)
  const current = segments.find((s) => s.id === selected)
  const chosenLabel = project.labels.some((l) => l.id === chosen) ? chosen : null
  const labelName = (id?: string) => project.labels.find((l) => l.id === id)?.name
  const doneCount = Object.keys(saved ?? {}).length
  const textRegions = kind === 'transcription' || kind === 'caption'

  /** What an item starts from: the answer already given, else the proposal of the model if the task has one. */
  const load = (i: number) => {
    const pr = saved?.[i] ? null : (proposed?.[i] ?? null)
    setProposal(pr)
    setDraft(saved?.[i] ?? pr?.answer ?? {})
  }
  useEffect(() => { load(0) }, [project.id])
  // A proposal can arrive while the item is on screen (the run is still going): take it if nothing was typed yet.
  useEffect(() => { if (!proposal && !saved?.[idx] && proposed?.[idx] && Object.keys(draft).length === 0) load(idx) }, [proposed?.[idx]])
  const go = (i: number) => { player.pause(); setIdx(i); load(i); setSelected(null); setMarkStart(null) }
  /** What makes a region worth keeping, according to the task. */
  const keep = (s: AudioSegment) =>
    kind === 'transcription' ? !!s.text?.trim() || !!s.label
    : kind === 'caption' ? !!s.text?.trim()
    : kind === 'classification' ? regionLabels(s).length > 0
    : task === 'regression' ? s.value !== undefined
    : true
  const submit = () => {
    const clean: Answer = { ...draft, captions: draft.captions?.filter((c) => c.trim()) }
    if (regionsMode) clean.segments = segments.filter(keep)
    commitAnswer(project.id, idx, clean, proposal)
    go(Math.min(rows.length - 1, idx + 1))
  }
  const setSegments = (segs: AudioSegment[]) => setDraft({ ...draft, segments: segs })
  const patchSeg = (id: string, p: Partial<AudioSegment>) => setSegments(segments.map((s) => (s.id === id ? { ...s, ...p } : s)))

  const create = (start: number, end: number, track = activeTrack) => {
    const first = kind === 'segments' ? (chosenLabel ?? project.labels[0]?.id) : chosenLabel
    const s: AudioSegment = { id: uid(), start, end, track, ...(first ? (kind === 'classification' ? { labels: [first] } : { label: first }) : {}) }
    setSegments([...segments, s])
    // A region with only a label is done; the others are selected so that their content can be filled in.
    setSelected(kind === 'segments' ? null : s.id)
  }
  const mark = () => {
    if (markStart === null) setMarkStart(player.time)
    else { if (Math.abs(player.time - markStart) >= 0.1) create(Math.min(markStart, player.time), Math.max(markStart, player.time)); setMarkStart(null) }
  }
  /** On a region, a label is applied to it (several for a classification, one otherwise); else it is the one given to the next region. */
  const chooseLabel = (id: string) => {
    if (!regionsMode) return kind === 'classification' ? setDraft(withLabel(draft, id, project.multiLabel)) : undefined
    setChosen(id)
    if (!current) return
    if (kind === 'classification') {
      const cur = regionLabels(current)
      const next = project.multiLabel ? (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]) : (cur.length === 1 && cur[0] === id ? [] : [id])
      patchSeg(current.id, { labels: next, label: undefined })
    } else patchSeg(current.id, { label: current.label === id ? undefined : id })
  }
  const removeSel = () => { if (selected) { setSegments(segments.filter((s) => s.id !== selected)); setSelected(null) } }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('textarea,input,select')) return
      const n = Number(e.key)
      if (e.key === ' ') { e.preventDefault(); player.toggle() }
      else if (e.key === 'ArrowLeft') player.seek(player.time - 1)
      else if (e.key === 'ArrowRight') player.seek(player.time + 1)
      else if (n >= 1 && n <= project.labels.length) chooseLabel(project.labels[n - 1].id)
      else if (regionsMode) {
        if (e.key === 'm') mark()
        else if (e.key === 'v') setTool('select')
        else if (e.key === 'r') setTool('region')
        else if (e.key === 'Delete' || e.key === 'Backspace') removeSel()
        else if (e.key === 'Escape') { setSelected(null); setMarkStart(null) }
        else if (e.key === 'Enter') submit()
      } else if (e.key === 'Enter' && kind !== 'caption') submit()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const labelButtons = (selectedIds: string[]) => (
    <div className="grid gap-1.5">
      {project.labels.map((l, i) => (
        <Button key={l.id} variant="outline" title={l.description} onClick={() => chooseLabel(l.id)} className={cn('h-auto justify-start gap-2 py-1.5 text-left whitespace-normal', selectedIds.includes(l.id) && 'ring-2 ring-primary')} style={selectedIds.includes(l.id) ? color(l.id) : undefined}>
          <kbd className="rounded bg-background/70 px-1.5 text-xs">{i + 1}</kbd>
          <span className="size-2.5 shrink-0 rounded-full" style={color(l.id)} />
          <span className="flex flex-col"><span>{l.name}</span>{l.description && <span className="text-xs font-normal opacity-80">{l.description}</span>}</span>
        </Button>
      ))}
    </div>
  )

  const captions = draft.captions?.length ? draft.captions : ['']
  const num = (v: string, fallback: number) => (Number.isFinite(Number(v)) && v !== '' ? Number(v) : fallback)
  const hint = markStart !== null ? t('datasets.annotation.audio.markStart', { t: fmt(markStart) })
    : regionsMode ? t(textRegions ? 'datasets.annotation.audio.hintTranscribe' : still ? 'datasets.annotation.series.hintSegments' : video ? 'datasets.annotation.video.hintSegments' : 'datasets.annotation.audio.hintSegments') : t(still ? 'datasets.annotation.series.hintPlain' : video ? 'datasets.annotation.video.hintPlain' : 'datasets.annotation.audio.hintPlain')
  const highlighted = regionsMode ? (current ? regionLabels(current) : chosenLabel ? [chosenLabel] : []) : labelsOf(draft)

  return (
    <Container className="max-w-7xl py-6">
      <Link to={`/datasets/${d.owner}/${d.name}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{d.owner}/{d.name}</Link>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <Badge variant="secondary">{t(`datasets.annotation.tasks.${task}.title`)}</Badge>
        {regionsMode && <Badge variant="outline">{t('datasets.annotation.audio.regionsBadge')}</Badge>}
        <span className="ml-auto text-sm text-muted-foreground">{t('datasets.annotation.progress', { done: doneCount, total: rows.length })}</span>
      </div>
      <div className="mt-2 flex gap-1">
        {rows.map((_, i) => <button key={i} aria-label={`#${i}`} onClick={() => go(i)} className={cn('h-1.5 flex-1 rounded-full', saved?.[i] ? 'bg-primary' : 'bg-muted', i === idx && 'ring-2 ring-ring ring-offset-1')} />)}
      </div>

      {proposal && <ProposalBanner proposal={proposal} edited={withOrigin({ ...draft, segments: regionsMode ? segments.filter(keep) : draft.segments }, proposal).origin === 'model_edited'} onAccept={submit} onReject={() => { rejectProposal(project.id, idx, proposal); setProposal(null); setDraft({}) }} />}

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {!still && (
            <Button size="icon" onClick={player.toggle} aria-label={t(player.playing ? 'datasets.annotation.audio.pause' : 'datasets.annotation.audio.play')}>{player.playing ? <Pause /> : <Play />}</Button>
            )}
            <span className="font-mono text-sm">{fmt(player.time)} / {fmt(duration)}</span>
            {!still && (
            <select aria-label={t('datasets.annotation.audio.speed')} value={player.speed} onChange={(e) => player.setSpeed(Number(e.target.value))} className="h-9 rounded-md border bg-background px-2 text-sm">
              {SPEEDS.map((s) => <option key={s} value={s}>×{s}</option>)}
            </select>
            )}
            <label className="flex items-center gap-2 text-sm text-muted-foreground">{t('datasets.annotation.audio.zoom')}
              <input type="range" min={1} max={8} step={1} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} className="accent-primary" />
            </label>
            {extra}
            {regionsMode && (
              <div className="ml-auto flex gap-1.5">
                <Button size="sm" variant={tool === 'select' ? 'default' : 'outline'} onClick={() => setTool('select')} title="V"><MousePointer2 />{t('datasets.annotation.audio.tools.select')}</Button>
                <Button size="sm" variant={tool === 'region' ? 'default' : 'outline'} onClick={() => setTool('region')} title="R"><SquareDashedMousePointer />{t('datasets.annotation.audio.tools.region')}</Button>
                <Button size="sm" variant={markStart === null ? 'outline' : 'default'} onClick={mark} title="M"><Flag />{t('datasets.annotation.audio.mark')} <kbd className="rounded bg-background/30 px-1 text-[10px]">M</kbd></Button>
              </div>
            )}
          </div>

          {view}

          <Waveform clip={clip} time={player.time} zoom={zoom} segments={regionsMode ? segments : []} tracks={regionsMode ? tracks : []} activeTrack={activeTrack} selectedId={selected} tool={regionsMode ? tool : 'select'}
            hueOf={(s) => { const l = regionLabels(s)[0]; return l ? hue(l) : null }}
            tagOf={(s) => regionLabels(s).map(labelName).filter(Boolean).join(', ') || (s.value !== undefined ? String(s.value) : s.text?.slice(0, 24)) || ''}
            onSeek={player.seek} onSelect={setSelected} onCreate={create} onChange={setSegments} onActiveTrack={setActiveTrack} />

          <p className="text-xs text-muted-foreground">{hint}</p>
          <p className="text-xs text-muted-foreground">{file} · {t('datasets.annotation.audio.duration', { s: duration })} · {t(still ? 'datasets.annotation.series.empty' : video ? 'datasets.annotation.video.empty' : 'datasets.annotation.audio.empty')}</p>
        </div>

        <aside className="space-y-4 rounded-lg border p-4 lg:sticky lg:top-4">
          {/* The whole clip */}
          {!regionsMode && kind === 'classification' && (
            <>
              {labelButtons(labelsOf(draft))}
              <div className="space-y-1.5">
                <label htmlFor="reason" className="text-sm font-medium">{t('datasets.annotation.reason')} <span className="font-normal text-muted-foreground">({t('datasets.annotation.optional')})</span></label>
                <Textarea id="reason" rows={2} placeholder={t('datasets.annotation.reasonPlaceholder')} value={draft.reason ?? ''} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
              </div>
            </>
          )}
          {!regionsMode && task === 'regression' && project.scale && (
            <>
              <ScaleInput scale={project.scale} value={draft.value} onChange={(value) => setDraft({ ...draft, value })} />
              <Textarea rows={2} aria-label={t('datasets.annotation.reason')} placeholder={t('datasets.annotation.reasonPlaceholder')} value={draft.reason ?? ''} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
            </>
          )}
          {!regionsMode && kind === 'caption' && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium">{t('datasets.annotation.image.caption')}</h3>
              {captions.map((c, i) => (
                <div key={i} className="flex gap-1.5">
                  <Textarea rows={3} aria-label={`${t('datasets.annotation.image.caption')} ${i + 1}`} placeholder={t('datasets.annotation.image.captionPlaceholder')} value={c} onChange={(e) => setDraft({ ...draft, captions: captions.map((x, j) => (j === i ? e.target.value : x)) })} />
                  {captions.length > 1 && <button aria-label={t('datasets.annotation.image.removeCaption')} onClick={() => setDraft({ ...draft, captions: captions.filter((_, j) => j !== i) })}><X className="size-4" /></button>}
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={() => setDraft({ ...draft, captions: [...captions, ''] })}><Plus />{t('datasets.annotation.image.addCaption')}</Button>
            </div>
          )}

          {/* Stretches of the clip */}
          {regionsMode && (
            <>
              {project.labels.length > 0 && labelButtons(highlighted)}
              <div className="flex gap-1.5">
                <Button variant="outline" size="sm" className="flex-1" onClick={() => create(player.time, Math.min(duration, player.time + 2))}><Plus />{t('datasets.annotation.audio.addHere')}</Button>
              </div>
              <div className="space-y-1.5">
                <h3 className="text-sm font-medium">{t('datasets.annotation.audio.segments')} · {segments.length}</h3>
                {!segments.length && <p className="text-xs text-muted-foreground">{t('datasets.annotation.audio.none')}</p>}
                <ul className="max-h-[28rem] space-y-1.5 overflow-y-auto">
                  {segments.map((s) => {
                    const sel = s.id === selected
                    return (
                      <li key={s.id} onClick={() => setSelected(s.id)} className={cn('space-y-1.5 rounded-md border p-2 text-sm', sel && 'ring-2 ring-primary')}>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {regionLabels(s).map((l) => <span key={l} className="rounded-full border px-2 py-0.5 text-xs font-medium" style={color(l)}>{labelName(l) ?? t('datasets.annotation.deletedLabel')}</span>)}
                          {s.value !== undefined && <span className="rounded-full border px-2 py-0.5 font-mono text-xs">{s.value}{project.scale?.unit && ` ${project.scale.unit}`}</span>}
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Input type="number" step={step ?? 0.1} min={0} max={duration} aria-label={t('datasets.annotation.audio.start')} className="h-7 w-20 px-1.5 font-mono text-xs" value={Number(s.start.toFixed(2))} onChange={(e) => patchSeg(s.id, { start: Math.min(num(e.target.value, s.start), s.end - 0.05) })} />
                          <span className="text-muted-foreground">→</span>
                          <Input type="number" step={step ?? 0.1} min={0} max={duration} aria-label={t('datasets.annotation.audio.end')} className="h-7 w-20 px-1.5 font-mono text-xs" value={Number(s.end.toFixed(2))} onChange={(e) => patchSeg(s.id, { end: Math.min(duration, Math.max(num(e.target.value, s.end), s.start + 0.05)) })} />
                          {tracks.length > 1 && (
                            <select aria-label={t('datasets.annotation.audio.track')} value={Math.min(s.track ?? 0, tracks.length - 1)} onChange={(e) => patchSeg(s.id, { track: Number(e.target.value) })} onClick={(e) => e.stopPropagation()} className="h-7 min-w-0 flex-1 rounded-md border bg-background px-1 text-xs">
                              {tracks.map((name, i) => <option key={i} value={i}>{name}</option>)}
                            </select>
                          )}
                          <span className="ml-auto" />
                          {!still && <button aria-label={t('datasets.annotation.audio.playSegment')} title={t('datasets.annotation.audio.playSegment')} onClick={(e) => { e.stopPropagation(); player.playRange(s.start, s.end) }}><Play className="size-4" /></button>}
                          <button aria-label="remove" onClick={(e) => { e.stopPropagation(); setSegments(segments.filter((x) => x.id !== s.id)); if (selected === s.id) setSelected(null) }}><Trash2 className="size-4" /></button>
                        </div>
                        {(textRegions || (sel && kind === 'segments')) && (
                          <Textarea rows={2} aria-label={t('datasets.annotation.audio.text')} placeholder={t('datasets.annotation.audio.textPlaceholder')} value={s.text ?? ''} autoFocus={sel && !s.text && textRegions}
                            onChange={(e) => patchSeg(s.id, { text: e.target.value })} />
                        )}
                        {sel && task === 'regression' && project.scale && <ScaleInput scale={project.scale} value={s.value} onChange={(value) => patchSeg(s.id, { value })} />}
                        {sel && (kind === 'classification' || kind === 'segments') && (
                          <Input className="h-8" aria-label={t('datasets.annotation.spanReason')} placeholder={t('datasets.annotation.spanReason')} value={s.reason ?? ''} onChange={(e) => patchSeg(s.id, { reason: e.target.value })} />
                        )}
                      </li>
                    )
                  })}
                </ul>
              </div>
            </>
          )}

          <div className="flex items-center justify-between border-t pt-3">
            <Button variant="ghost" onClick={() => go(Math.min(rows.length - 1, idx + 1))}><SkipForward />{t('datasets.annotation.skip')}</Button>
            <Button onClick={submit}><Check />{t('datasets.annotation.submit')}</Button>
          </div>
        </aside>
      </div>
    </Container>
  )
}
