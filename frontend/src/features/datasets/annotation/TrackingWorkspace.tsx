import { ArrowLeft, Check, ChevronLeft, ChevronRight, Diamond, EyeOff, MousePointer2, Pause, Play, SkipForward, SquareDashed, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { VideoFrame } from '../components/viewers/VideoFrame'
import { hue } from '../components/viewers/seed'
import type { Dataset } from '../mockData'
import { fmtTime } from './audioMock'
import { useAnnotations, commitAnswer, rejectProposal, type Answer, type Proposal, type AnnotationProject, type Keyframe, type ObjectTrack, withOrigin } from './store'
import { ProposalBanner } from './ProposalBanner'
import { color } from './ui'
import { useClockPlayer } from './useClockPlayer'
import { VIDEO_H as H, VIDEO_W as W } from './videoMock'

const FPS = 25
const SPEEDS = [0.25, 0.5, 1, 2]
type Box = Keyframe['box']
const uid = () => Math.random().toString(36).slice(2, 8)
const clamp = (n: number) => Math.min(1, Math.max(0, n))
const quantize = (t: number) => Math.round(t * FPS) / FPS
const at = (k: Keyframe, t: number) => Math.abs(k.t - t) < 0.5 / FPS
const stroke = (label: string) => `hsl(${hue(label)} 75% 45%)`

/** Where the box of a track is at time `t`: interpolated between two keyframes, held after the last, hidden once it left the frame. */
function boxAt(track: ObjectTrack, t: number): Box | null {
  const k = [...track.keyframes].sort((a, b) => a.t - b.t)
  if (!k.length || t < k[0].t - 1e-6) return null
  const i = k.findIndex((x) => x.t > t + 1e-6)
  const a = i < 0 ? k[k.length - 1] : k[i - 1]
  const b = i < 0 ? undefined : k[i]
  if (a.outside) return null
  if (!b || b.outside) return a.box
  const f = (t - a.t) / (b.t - a.t)
  return a.box.map((v, j) => v + (b.box[j] - v) * f) as Box
}

/** The stretches during which a track is visible, in seconds. */
function visibleSpans(track: ObjectTrack, duration: number): [number, number][] {
  const k = [...track.keyframes].sort((a, b) => a.t - b.t)
  return k.flatMap((x, i): [number, number][] => (x.outside ? [] : [[x.t, k[i + 1]?.t ?? duration]]))
}

type Drag = { kind: 'new'; p0: [number, number] } | { kind: 'move'; id: string; p0: [number, number]; box: Box } | { kind: 'resize'; id: string; corner: number; box: Box }

/**
 * Tracking: draw a box around an object, move forward in time, correct the box when it drifts: each correction is a
 * keyframe and the box is interpolated between keyframes. A track can be marked as having left the frame.
 */
export function TrackingWorkspace({ dataset: d, project }: { dataset: Dataset; project: AnnotationProject }) {
  const { t } = useTranslation()
  const store = useAnnotations()
  const saved = store.answers[project.id]
  const proposed = store.proposals[project.id]
  const rows = d.sample
  const [idx, setIdx] = useState(0)
  const [draft, setDraft] = useState<Answer>(() => saved?.[0] ?? {})
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [tool, setTool] = useState<'select' | 'box'>('box')
  const [chosen, setChosen] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [preview, setPreview] = useState<Box | null>(null)
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<Drag | null>(null)

  const [file, duration] = [String(rows[idx][0]), Number(rows[idx][2])]
  const player = useClockPlayer(duration, FPS)
  const time = quantize(player.time)
  const tracks = draft.tracks ?? []
  const active = project.labels.some((l) => l.id === chosen) ? chosen : (project.labels[0]?.id ?? null)
  const labelName = (id: string) => project.labels.find((l) => l.id === id)?.name ?? t('datasets.annotation.deletedLabel')
  const sel = tracks.find((x) => x.id === selected)
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
  const go = (i: number) => { player.pause(); setIdx(i); load(i); setSelected(null) }
  const submit = () => { commitAnswer(project.id, idx, draft, proposal); go(Math.min(rows.length - 1, idx + 1)) }
  const setTracks = (next: ObjectTrack[]) => setDraft({ ...draft, tracks: next })
  const patchTrack = (id: string, fn: (x: ObjectTrack) => ObjectTrack) => setTracks(tracks.map((x) => (x.id === id ? fn(x) : x)))
  /** Writes the box of a track at the current time: it replaces the keyframe there, or adds one. */
  const setKeyframe = (id: string, box: Box, outside = false) =>
    patchTrack(id, (x) => ({ ...x, keyframes: [...x.keyframes.filter((k) => !at(k, time)), { t: time, box, outside }].sort((a, b) => a.t - b.t) }))
  const lastBox = (x: ObjectTrack): Box => [...x.keyframes].reverse().find((k) => !k.outside)?.box ?? [0.4, 0.4, 0.6, 0.6]

  const toNorm = (e: PointerEvent): [number, number] => {
    const s = svg.current!
    const pt = s.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY
    const p = pt.matrixTransform(s.getScreenCTM()!.inverse())
    return [clamp(p.x / W), clamp(p.y / H)]
  }
  const down = (e: PointerEvent) => {
    player.pause()
    if (tool === 'box') { svg.current!.setPointerCapture(e.pointerId); const p = toNorm(e); drag.current = { kind: 'new', p0: p }; setPreview([p[0], p[1], p[0], p[1]]) }
    else setSelected(null)
  }
  const startMove = (e: PointerEvent, id: string, box: Box) => {
    if (tool !== 'select') return
    e.stopPropagation(); player.pause(); svg.current!.setPointerCapture(e.pointerId)
    setSelected(id); drag.current = { kind: 'move', id, p0: toNorm(e), box }
  }
  const startResize = (e: PointerEvent, id: string, corner: number, box: Box) => {
    e.stopPropagation(); player.pause(); svg.current!.setPointerCapture(e.pointerId)
    drag.current = { kind: 'resize', id, corner, box }
  }
  const move = (e: PointerEvent) => {
    const g = drag.current
    if (!g) return
    const p = toNorm(e)
    if (g.kind === 'new') setPreview([Math.min(g.p0[0], p[0]), Math.min(g.p0[1], p[1]), Math.max(g.p0[0], p[0]), Math.max(g.p0[1], p[1])])
    else if (g.kind === 'move') {
      const dx = p[0] - g.p0[0], dy = p[1] - g.p0[1], w = g.box[2] - g.box[0], h = g.box[3] - g.box[1]
      const x1 = Math.min(1 - w, Math.max(0, g.box[0] + dx)), y1 = Math.min(1 - h, Math.max(0, g.box[1] + dy))
      setKeyframe(g.id, [x1, y1, x1 + w, y1 + h])
    } else {
      // Corners: 0 top left, 1 top right, 2 bottom right, 3 bottom left. The opposite corner stays where it is.
      const [x1, y1, x2, y2] = g.box
      const fx = g.corner === 0 || g.corner === 3 ? x2 : x1, fy = g.corner < 2 ? y2 : y1
      setKeyframe(g.id, [Math.min(fx, p[0]), Math.min(fy, p[1]), Math.max(fx, p[0]), Math.max(fy, p[1])])
    }
  }
  const up = () => {
    const g = drag.current
    drag.current = null
    if (g?.kind === 'new' && preview && active && preview[2] - preview[0] > 0.01 && preview[3] - preview[1] > 0.01) {
      const id = uid()
      setTracks([...tracks, { id, label: active, keyframes: [{ t: time, box: preview }] }])
      setSelected(id)
    }
    setPreview(null)
  }

  const keyTimes = sel ? [...sel.keyframes].map((k) => k.t).sort((a, b) => a - b) : []
  const jump = (dir: 1 | -1) => {
    const target = dir === 1 ? keyTimes.find((k) => k > time + 1e-6) : [...keyTimes].reverse().find((k) => k < time - 1e-6)
    if (target !== undefined) player.seek(target)
  }
  const kfHere = sel?.keyframes.find((k) => at(k, time))
  const toggleOutside = () => {
    if (!sel) return
    if (kfHere?.outside) patchTrack(sel.id, (x) => ({ ...x, keyframes: x.keyframes.filter((k) => k !== kfHere) }))
    else setKeyframe(sel.id, boxAt(sel, time) ?? lastBox(sel), true)
  }
  const removeKeyframe = () => { if (sel && kfHere && sel.keyframes.length > 1) patchTrack(sel.id, (x) => ({ ...x, keyframes: x.keyframes.filter((k) => k !== kfHere) })) }
  const chooseLabel = (id: string) => { setChosen(id); if (tool === 'select' && sel) patchTrack(sel.id, (x) => ({ ...x, label: id })) }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('textarea,input,select')) return
      const n = Number(e.key)
      if (e.key === ' ') { e.preventDefault(); player.toggle() }
      else if (e.key === ',') player.step(-1)
      else if (e.key === '.') player.step(1)
      else if (n >= 1 && n <= project.labels.length) chooseLabel(project.labels[n - 1].id)
      else if (e.key === 'v') setTool('select')
      else if (e.key === 'b') setTool('box')
      else if (e.key === 'Escape') setSelected(null)
      else if (e.key === 'Enter') submit()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const tl = useRef<HTMLDivElement>(null)
  const seekAt = (e: PointerEvent) => { const r = tl.current!.getBoundingClientRect(); player.seek(((e.clientX - r.left) / r.width) * duration) }
  const pct = (s: number) => `${(s / duration) * 100}%`

  return (
    <Container className="max-w-7xl py-6">
      <Link to={`/datasets/${d.owner}/${d.name}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{d.owner}/{d.name}</Link>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <Badge variant="secondary">{t(`datasets.annotation.tasks.${project.task}.title`)}</Badge>
        <span className="ml-auto text-sm text-muted-foreground">{t('datasets.annotation.progress', { done: doneCount, total: rows.length })}</span>
      </div>
      <div className="mt-2 flex gap-1">
        {rows.map((_, i) => <button key={i} aria-label={`#${i}`} onClick={() => go(i)} className={cn('h-1.5 flex-1 rounded-full', saved?.[i] ? 'bg-primary' : 'bg-muted', i === idx && 'ring-2 ring-ring ring-offset-1')} />)}
      </div>

      {proposal && <ProposalBanner proposal={proposal} edited={withOrigin(draft, proposal).origin === 'model_edited'} onAccept={submit} onReject={() => { rejectProposal(project.id, idx, proposal); setProposal(null); setDraft({}) }} />}

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-3">
          <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="block w-full touch-none select-none rounded-lg border bg-muted" style={{ cursor: tool === 'box' ? 'crosshair' : 'default' }}
            onPointerDown={down} onPointerMove={move} onPointerUp={up}>
            <VideoFrame file={file} t={time}>
              {tracks.map((x) => {
                const b = boxAt(x, time)
                if (!b) return null
                const on = x.id === selected, c = stroke(x.label)
                const [x1, y1, x2, y2] = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
                const keyed = x.keyframes.some((k) => at(k, time))
                return (
                  <g key={x.id}>
                    <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill={c} fillOpacity={on ? 0.2 : 0.1} stroke={c} strokeWidth={on ? 4 : 3} strokeDasharray={keyed ? undefined : '10 6'} vectorEffect="non-scaling-stroke"
                      style={{ pointerEvents: tool === 'select' ? 'auto' : 'none', cursor: 'move' }} onPointerDown={(e) => startMove(e, x.id, b)} />
                    <g pointerEvents="none">
                      <rect x={x1} y={y1 - H * 0.045} width={labelName(x.label).length * W * 0.0105 + W * 0.014} height={H * 0.045} fill={c} />
                      <text x={x1 + W * 0.007} y={y1 - H * 0.013} fill="white" fontSize={H * 0.03} fontWeight={600}>{labelName(x.label)}</text>
                    </g>
                    {on && tool === 'select' && ([[x1, y1], [x2, y1], [x2, y2], [x1, y2]] as const).map(([cx, cy], i) => (
                      <circle key={i} cx={cx} cy={cy} r={W * 0.008} fill="white" stroke={c} strokeWidth={2} vectorEffect="non-scaling-stroke" style={{ cursor: 'nwse-resize' }} onPointerDown={(e) => startResize(e, x.id, i, b)} />
                    ))}
                  </g>
                )
              })}
              {preview && <rect x={preview[0] * W} y={preview[1] * H} width={(preview[2] - preview[0]) * W} height={(preview[3] - preview[1]) * H} fill="white" fillOpacity={0.15} stroke="white" strokeWidth={2} strokeDasharray="8 5" vectorEffect="non-scaling-stroke" pointerEvents="none" />}
            </VideoFrame>
          </svg>

          <div className="flex flex-wrap items-center gap-2">
            <Button size="icon" onClick={player.toggle} aria-label={t(player.playing ? 'datasets.annotation.audio.pause' : 'datasets.annotation.audio.play')}>{player.playing ? <Pause /> : <Play />}</Button>
            <Button size="icon" variant="outline" aria-label={t('datasets.annotation.video.prevFrame')} title="," onClick={() => player.step(-1)}><ChevronLeft /></Button>
            <Button size="icon" variant="outline" aria-label={t('datasets.annotation.video.nextFrame')} title="." onClick={() => player.step(1)}><ChevronRight /></Button>
            <span className="font-mono text-sm">{fmtTime(time)} / {fmtTime(duration)}</span>
            <select aria-label={t('datasets.annotation.audio.speed')} value={player.speed} onChange={(e) => player.setSpeed(Number(e.target.value))} className="h-9 rounded-md border bg-background px-2 text-sm">
              {SPEEDS.map((s) => <option key={s} value={s}>×{s}</option>)}
            </select>
            <div className="ml-auto flex gap-1.5">
              <Button size="sm" variant={tool === 'select' ? 'default' : 'outline'} onClick={() => setTool('select')} title="V"><MousePointer2 />{t('datasets.annotation.audio.tools.select')}</Button>
              <Button size="sm" variant={tool === 'box' ? 'default' : 'outline'} onClick={() => setTool('box')} title="B"><SquareDashed />{t('datasets.annotation.video.box')}</Button>
            </div>
          </div>

          {/* One row per track: where it is visible, and its keyframes. */}
          <div ref={tl} className="relative overflow-hidden rounded-lg border" onPointerDown={seekAt}>
            <div className="pointer-events-none h-6 border-b bg-muted/40" />
            {tracks.map((x) => (
              <div key={x.id} className={cn('relative h-8 border-b last:border-b-0', x.id === selected && 'bg-primary/5')}>
                {visibleSpans(x, duration).map(([a, b], i) => <span key={i} className="absolute top-2 bottom-2 rounded-sm" style={{ left: pct(a), width: pct(b - a), background: stroke(x.label), opacity: 0.35 }} />)}
                {x.keyframes.map((k, i) => (
                  <button key={i} aria-label={fmtTime(k.t)} onPointerDown={(e) => { e.stopPropagation(); setSelected(x.id); player.seek(k.t) }}
                    className={cn('absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border', k.outside ? 'bg-background' : '')} style={{ left: pct(k.t), borderColor: stroke(x.label), background: k.outside ? undefined : stroke(x.label) }} />
                ))}
              </div>
            ))}
            {!tracks.length && <div className="p-2 text-xs text-muted-foreground">{t('datasets.annotation.video.noTrack')}</div>}
            <div className="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-primary" style={{ left: pct(time) }} />
          </div>
          <p className="text-xs text-muted-foreground">{t('datasets.annotation.video.hintTracking')}</p>
          <p className="text-xs text-muted-foreground">{file} · {t('datasets.annotation.audio.duration', { s: duration })} · {t('datasets.annotation.video.empty')}</p>
        </div>

        <aside className="space-y-4 rounded-lg border p-4 lg:sticky lg:top-4">
          <div className="grid gap-1.5">
            {project.labels.map((l, i) => {
              const on = (tool === 'select' && sel ? sel.label : active) === l.id
              return (
                <Button key={l.id} variant="outline" title={l.description} onClick={() => chooseLabel(l.id)} className={cn('h-auto justify-start gap-2 py-1.5 text-left whitespace-normal', on && 'ring-2 ring-primary')} style={on ? color(l.id) : undefined}>
                  <kbd className="rounded bg-background/70 px-1.5 text-xs">{i + 1}</kbd>
                  <span className="size-2.5 shrink-0 rounded-full" style={color(l.id)} />
                  <span className="flex flex-col"><span>{l.name}</span>{l.description && <span className="text-xs font-normal opacity-80">{l.description}</span>}</span>
                </Button>
              )
            })}
          </div>

          {sel && (
            <div className="space-y-2 rounded-md border p-2">
              <div className="flex items-center gap-1.5 text-sm font-medium"><span className="size-2.5 rounded-full" style={{ background: stroke(sel.label) }} />{labelName(sel.label)}</div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" onClick={() => jump(-1)} disabled={!keyTimes.some((k) => k < time - 1e-6)}><ChevronLeft />{t('datasets.annotation.video.prevKey')}</Button>
                <Button size="sm" variant="outline" onClick={() => jump(1)} disabled={!keyTimes.some((k) => k > time + 1e-6)}>{t('datasets.annotation.video.nextKey')}<ChevronRight /></Button>
                <Button size="sm" variant={kfHere?.outside ? 'default' : 'outline'} onClick={toggleOutside}><EyeOff />{t('datasets.annotation.video.outside')}</Button>
                <Button size="sm" variant="ghost" disabled={!kfHere || sel.keyframes.length < 2} onClick={removeKeyframe}><Diamond />{t('datasets.annotation.video.removeKey')}</Button>
              </div>
              <Input className="h-8" aria-label={t('datasets.annotation.spanReason')} placeholder={t('datasets.annotation.spanReason')} value={sel.reason ?? ''} onChange={(e) => patchTrack(sel.id, (x) => ({ ...x, reason: e.target.value }))} />
            </div>
          )}

          <div className="space-y-1.5">
            <h3 className="text-sm font-medium">{t('datasets.annotation.video.tracks')} · {tracks.length}</h3>
            <ul className="max-h-60 space-y-1 overflow-y-auto">
              {tracks.map((x, n) => (
                <li key={x.id} onClick={() => { setSelected(x.id); setTool('select') }} className={cn('flex items-center gap-2 rounded-md border p-2 text-sm', x.id === selected && 'ring-2 ring-primary')}>
                  <span className="rounded-full border px-2 py-0.5 text-xs font-medium" style={color(x.label)}>{labelName(x.label)} {n + 1}</span>
                  <span className="text-xs text-muted-foreground">{t('datasets.annotation.video.keyframes', { n: x.keyframes.length })}</span>
                  <button className="ml-auto" aria-label="remove" onClick={(e) => { e.stopPropagation(); setTracks(tracks.filter((y) => y.id !== x.id)); if (selected === x.id) setSelected(null) }}><Trash2 className="size-4" /></button>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex items-center justify-between border-t pt-3">
            <Button variant="ghost" onClick={() => go(Math.min(rows.length - 1, idx + 1))}><SkipForward />{t('datasets.annotation.skip')}</Button>
            <Button onClick={submit}><Check />{t('datasets.annotation.submit')}</Button>
          </div>
        </aside>
      </div>
    </Container>
  )
}
