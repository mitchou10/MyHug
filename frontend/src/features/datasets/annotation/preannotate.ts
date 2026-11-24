import { sceneLayout } from '../components/viewers/SceneGraphics'
import { seeded } from '../components/viewers/seed'
import type { Dataset } from '../mockData'
import { clipFor } from './audioMock'
import { modelInfo } from './models'
import { seriesFor } from './seriesMock'
import { DEFAULT_TRACKS, usesRegions, type Answer, type AnnotationProject, type AudioSegment, type CellNote, type ColumnNote, type ImageObject, type Proposal, type Pt } from './store'
import { shapesAt, VIDEO_H, VIDEO_W } from './videoMock'

/**
 * A stand-in for the models that will pre-annotate: it makes up plausible, repeatable proposals from the data, so the
 * interface for checking them can be built before any model exists. A real model replaces `proposalFor`, nothing else.
 */
/** The proposal a model makes for an item of a task. A real model replaces this function, nothing else. */
export function makeProposal(project: AnnotationProject, d: Dataset, idx: number, model: string, runId: string): Proposal | null {
  return build(project, d, idx, model, runId)
}

/** How many items a task has, for every kind of dataset. */
export const itemCount = (d: Dataset) => (d.modality === 'timeseries' ? (d.collection?.length ?? 0) : d.sample.length)

const snap = (v: number, step: number) => Number((Math.round(v / step) * step).toFixed(6))
const clamp01 = (n: number) => Math.min(1, Math.max(0, n))

function build(project: AnnotationProject, d: Dataset, idx: number, model: string, runId: string): Proposal | null {
  const series = d.modality === 'timeseries'
  const row = series ? undefined : d.sample[idx]
  const coll = series ? d.collection?.[idx] : undefined
  if (!row && !coll) return null
  const id = coll?.id ?? String(row![0])
  const duration = coll ? coll.points - 1 : Number(row?.[2] ?? 0)
  const rnd = seeded(`${project.id}:${model}:${id}`)
  const labels = project.labels
  const pick = () => labels[Math.floor(rnd() * labels.length)]?.id
  const pickMany = () => [...new Set([pick(), project.multiLabel ? pick() : undefined])].filter((x): x is string => !!x)
  // A better model sounds more sure of itself.
  const quality = modelInfo(model)?.quality ?? 0.6
  const confidence = Math.round(Math.min(0.99, quality - 0.25 + rnd() * 0.3) * 100) / 100
  const task = project.task
  const kind = task.replace(/^(audio|video|timeseries|image)_/, '')
  let answer: Answer | null = null

  // Stretches of a clip or series: classification, segments, transcription, description, scores.
  const regions = (): AudioSegment[] => {
    const tracks = project.tracks?.length ?? DEFAULT_TRACKS.length
    return stretches(d, id, duration, rnd).map(([start, end], i) => {
      const s: AudioSegment = { id: `r${i}`, start, end, track: i % tracks }
      if (kind === 'classification') s.labels = pickMany()
      else if (kind === 'segments') s.label = pick()
      else if (kind === 'transcription') s.text = 'Texte proposé par le modèle, à vérifier.'
      else if (kind === 'caption') s.text = `Passage ${i + 1} (proposé par le modèle).`
      else if (task === 'regression' && project.scale) s.value = snap(project.scale.min + rnd() * (project.scale.max - project.scale.min), project.scale.step)
      return s
    })
  }

  if (task === 'ner') answer = ner(project, d, row!)
  else if (task === 'qa') answer = qa(d, row!)
  else if (task === 'cell_review') answer = cellReview(project, d, idx)
  else if (task === 'column_schema') answer = idx === 0 ? columnSchema(project, d) : null
  else if (task === 'image_detection' || task === 'image_segmentation' || task === 'image_polyline' || task === 'image_keypoints') answer = image(project, id, Number(row![1]), Number(row![2]), pick)
  else if (task === 'image_vqa') answer = { qa: [{ id: 'q0', question: 'Que voit-on sur cette image ?', answer: 'Une scène extérieure avec plusieurs objets.', sources: [] }] }
  else if (task === 'video_tracking') answer = tracking(project, id, duration)
  else if (task === 'regression' && project.scale && !usesRegions(project)) answer = { value: snap(project.scale.min + rnd() * (project.scale.max - project.scale.min), project.scale.step) }
  else if (usesRegions(project)) answer = { segments: regions() }
  else if (kind === 'caption') answer = { captions: [`Description proposée par le modèle pour ${id}.`] }
  else if (labels.length) answer = pickMany().length > 1 || project.multiLabel ? { labels: pickMany() } : { label: pick() }

  const empty = !answer || Object.values(answer).every((v) => v === undefined || (Array.isArray(v) && !v.length) || (typeof v === 'object' && v !== null && !Array.isArray(v) && !Object.keys(v).length))
  return empty ? null : { answer: answer!, model, confidence, runId }
}

/** Where something happens in a sound or a series (peaks, outliers), or three even parts when nothing stands out. */
function stretches(d: Dataset, id: string, duration: number, rnd: () => number): [number, number][] {
  let values: number[] = [], threshold = 0
  if (d.modality === 'audio') { values = clipFor(id, duration).peaks; threshold = 0.3 }
  else if (d.modality === 'timeseries') {
    const v = seriesFor(id, duration + 1), mean = v.reduce((a, b) => a + b, 0) / v.length
    const sd = Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / v.length) || 1
    values = v.map((x) => Math.abs(x - mean) / sd); threshold = 1.3
  }
  const out: [number, number][] = []
  const at = (i: number) => (i / Math.max(1, values.length - 1)) * duration
  let from = -1, last = -1
  values.forEach((v, i) => {
    if (v > threshold) { if (from < 0) from = i; last = i }
    else if (from >= 0 && i - last > 2) { out.push([at(from), at(last + 1)]); from = -1 }
  })
  if (from >= 0) out.push([at(from), at(last + 1)])
  const found = out.filter(([a, b]) => b - a >= 0.1).slice(0, 6).map(([a, b]) => [Number(a.toFixed(2)), Number(b.toFixed(2))] as [number, number])
  if (found.length) return found
  const k = 3, jitter = rnd() * 0.03
  return Array.from({ length: k }, (_, i): [number, number] => [Number(((i / k + jitter) * duration).toFixed(2)), Number((((i + 0.8) / k) * duration).toFixed(2))])
}

function ner(project: AnnotationProject, d: Dataset, row: (string | number)[]): Answer | null {
  const text = String(row[Math.max(0, d.columns.findIndex((c) => c === 'text' || c === 'question'))])
  const tokens = text.split(/\s+/).filter(Boolean)
  const entity = project.labels.find((l) => (l.kind ?? 'entity') === 'entity' && (l.valueType ?? 'text') === 'text') ?? project.labels[0]
  const date = project.labels.find((l) => l.valueType === 'date')
  const semantic = project.labels.find((l) => l.kind === 'semantic')
  const spans: NonNullable<Answer['spans']> = []
  for (let i = 0; i < tokens.length; i++) {
    const tok = tokens[i]
    if (date && /^\d{4}$/.test(tok)) spans.push({ start: i, end: i, label: date.id })
    else if (entity && i > 0 && /^[A-ZÀ-Ý][\p{L}-]+/u.test(tok)) { const j = /^[A-ZÀ-Ý]/.test(tokens[i + 1] ?? '') ? i + 1 : i; spans.push({ start: i, end: j, label: entity.id }); i = j }
    else if (semantic && /condamn|amende|relax|emprisonn|vol|violence/i.test(tok)) spans.push({ start: i, end: Math.min(tokens.length - 1, i + 2), label: semantic.id })
  }
  return spans.length ? { spans } : null
}

function qa(d: Dataset, row: (string | number)[]): Answer {
  const text = String(row[Math.max(0, d.columns.findIndex((c) => c === 'text' || c === 'question'))])
  const n = text.split(/\s+/).filter(Boolean).length
  const end = Math.min(n - 1, 7)
  return { qa: [{ id: 'q0', question: 'De quoi parle ce texte ?', answer: text.split(/\s+/).slice(0, end + 1).join(' '), answerSpan: { start: 0, end }, sources: [{ start: 0, end }] }] }
}

function image(project: AnnotationProject, file: string, W: number, H: number, pick: () => string | undefined): Answer {
  const { horizon, shapes } = sceneLayout(file, W, H)
  const box = (s: (typeof shapes)[number]): Pt[] => [[s.x / W, (horizon - s.h) / H], [(s.x + s.w) / W, (horizon - s.h) / H], [(s.x + s.w) / W, horizon / H], [s.x / W, horizon / H]].map(([x, y]) => [clamp01(x), clamp01(y)] as Pt)
  if (project.task === 'image_polyline') return { objects: [{ id: 'o0', label: pick() ?? '', points: [[0, horizon / H], [0.5, horizon / H + 0.01], [1, horizon / H]] }] }
  if (project.task === 'image_keypoints') {
    const [a, b, c, e] = box(shapes[0])
    const spots: Pt[] = [a, b, c, e, [(a[0] + b[0]) / 2, c[1]]]
    return { instances: [{ id: 'i0', points: project.labels.slice(0, spots.length).map((l, i) => ({ label: l.id, point: spots[i] })) }] }
  }
  const objects: ImageObject[] = shapes.slice(0, project.task === 'image_segmentation' ? 5 : 4).map((s, i) => ({ id: `o${i}`, label: pick() ?? '', points: box(s) }))
  return { objects }
}

function tracking(project: AnnotationProject, file: string, duration: number): Answer {
  const at = (t: number) => shapesAt(file, t)
  const box = (s: ReturnType<typeof shapesAt>[number]): [number, number, number, number] => [clamp01(s.x / VIDEO_W), clamp01(s.y / VIDEO_H), clamp01((s.x + s.w) / VIDEO_W), clamp01((s.y + s.h) / VIDEO_H)]
  return {
    tracks: [0, 1, 2].map((i) => ({
      id: `t${i}`, label: project.labels[i % project.labels.length]?.id ?? '',
      // The model gives a few keyframes: the box between them is interpolated, so it drifts a little.
      keyframes: [0, duration / 2, duration].map((t) => ({ t: Number(t.toFixed(2)), box: box(at(t)[i]) })),
    })),
  }
}

function cellReview(project: AnnotationProject, d: Dataset, r: number): Answer | null {
  const byName = (part: string) => project.labels.find((l) => l.name.toLowerCase().includes(part))?.id ?? project.labels[0]?.id
  const cells: Record<number, CellNote> = {}
  const row = d.sample[r]
  d.columns.forEach((_, j) => {
    const v = row[j]
    const col = d.sample.map((x) => x[j]).filter((x): x is number => typeof x === 'number').sort((a, b) => a - b)
    const median = col.length ? col[Math.floor(col.length / 2)] : 0
    if (v === '' || v === 'n/a') cells[j] = { issue: byName('manq') }
    else if (typeof v === 'number' && v < 0) cells[j] = { issue: byName('erreur'), corrected: String(Math.abs(v)) }
    else if (typeof v === 'number' && median > 0 && (v > median * 3 || v < median / 8)) cells[j] = { issue: byName('aberr') }
    else if (typeof v === 'string' && v !== v.trim()) cells[j] = { issue: byName('format'), corrected: v.trim().replace(/^./, (c) => c.toUpperCase()) }
  })
  return Object.keys(cells).length ? { cells } : null
}

function columnSchema(project: AnnotationProject, d: Dataset): Answer {
  const byName = (part: string) => project.labels.find((l) => l.name.toLowerCase().includes(part))?.id
  const columns: Record<number, ColumnNote> = {}
  d.columns.forEach((name, j) => {
    const values = d.sample.map((r) => r[j])
    const numeric = values.filter((v) => typeof v === 'number').length > values.length / 2
    const unique = new Set(values).size === values.length
    columns[j] = /^id$|_id$/.test(name) && unique ? { role: byName('identif'), valueType: 'identifier', formats: ['D+'] }
      : /price|prix|eur|amount/.test(name) ? { role: byName('cible'), valueType: 'amount', formats: ['D+'], unit: '€' }
      : numeric ? { role: byName('mesure'), valueType: 'number', formats: ['D+'] }
      : { role: byName('cat'), valueType: 'text' }
  })
  return { columns }
}
