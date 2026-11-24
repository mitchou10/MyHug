import { Play } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { sceneLayout, SceneGraphics } from '@/features/datasets/components/viewers/SceneGraphics'
import { hue, seeded } from '@/features/datasets/components/viewers/seed'
import { DATASETS } from '@/features/datasets/mockData'
import { cn } from '@/lib/utils'
import type { Model } from '../mockData'

type Result =
  | { kind: 'scores'; items: { label: string; score: number }[] }
  | { kind: 'spans'; tokens: string[]; spans: { start: number; end: number; label: string }[] }
  | { kind: 'text'; text: string }
  | { kind: 'value'; value: number }
  | { kind: 'boxes'; file: string; boxes: { x: number; y: number; w: number; h: number; label: string }[] }
  | { kind: 'lines'; lines: string[] }

/** What a model would answer. A stand-in: plausible and repeatable, until a backend runs the real model. */
function predict(model: Model, input: string): Result {
  const rnd = seeded(`${model.name}:${input}`)
  const task = model.tasks[0] ?? 'classification'
  const scores = (labels: string[]) => {
    const w = labels.map(() => rnd() ** 2 + 0.05), sum = w.reduce((a, b) => a + b, 0)
    return { kind: 'scores' as const, items: labels.map((label, i) => ({ label, score: w[i] / sum })).sort((a, b) => b.score - a.score) }
  }
  if (task === 'ner') {
    const tokens = input.split(/\s+/).filter(Boolean)
    const spans: { start: number; end: number; label: string }[] = []
    tokens.forEach((tok, i) => {
      if (/^\d{4}$/.test(tok)) spans.push({ start: i, end: i, label: 'DATE' })
      else if (i > 0 && /^[A-ZÀ-Ý][\p{L}-]+$/u.test(tok)) spans.push({ start: i, end: i, label: 'PERSONNE' })
    })
    return { kind: 'spans', tokens, spans }
  }
  if (task === 'qa') return { kind: 'text', text: input.split(/\s+/).slice(0, 7).join(' ') }
  if (task === 'regression') return { kind: 'value', value: Number((rnd() * 10).toFixed(1)) }
  if (task === 'image_detection' || task === 'image_segmentation' || task === 'image_keypoints' || task === 'image_polyline') {
    const { horizon, shapes } = sceneLayout(input, 1280, 720)
    return { kind: 'boxes', file: input, boxes: shapes.slice(0, 4).map((s, i) => ({ x: s.x, y: horizon - s.h, w: s.w, h: s.h, label: ['stop', 'danger', 'vitesse', 'interdiction'][i] })) }
  }
  if (task === 'image_caption' || task === 'audio_caption' || task === 'video_caption' || task === 'timeseries_caption') return { kind: 'text', text: `Description proposée pour ${input}.` }
  if (task === 'audio_transcription') return { kind: 'lines', lines: ['0:01.2 → 0:04.8  Bonjour, je vous appelle au sujet de ma facture.', '0:05.1 → 0:09.6  Bien sûr, pouvez-vous me donner votre numéro de client ?'] }
  if (task === 'audio_segments' || task === 'video_segments') return { kind: 'lines', lines: ['0:00.8 → 0:03.1  segment 1', '0:04.0 → 0:07.4  segment 2', '0:08.2 → 0:10.0  segment 3'] }
  if (task === 'video_tracking') return { kind: 'lines', lines: ['3 objets suivis', 'objet 1 : 4 images clés', 'objet 2 : 3 images clés', 'objet 3 : 3 images clés'] }
  if (task === 'timeseries_segments') return { kind: 'lines', lines: ['2023-04-09 → 2023-04-23  anomalie', '2023-12-24 → 2023-12-31  anomalie'] }
  if (task === 'cell_review') return { kind: 'lines', lines: ['ligne 7 · surface_m2 : aberrante', 'ligne 10 · price_eur : manquante', 'ligne 13 · price_eur : erreur'] }
  if (task === 'column_schema') return { kind: 'lines', lines: ['id : identifiant', 'surface_m2 : mesure', 'city : catégorie', 'price_eur : cible'] }
  return scores(['positive', 'neutral', 'negative'])
}

const TEXT_SAMPLES = ['Le tribunal de Lyon a condamné Jean Dupont le 12 mars 2023 à huit mois de prison avec sursis.', 'Un film magnifique, je recommande vivement ce chef-d’œuvre !']
const IMAGES = ['img_0001.jpg', 'img_0002.jpg', 'img_0003.jpg']

/** "Try it": give an input to a model and see what it answers. */
export function ModelWidget({ model }: { model: Model }) {
  const { t } = useTranslation()
  const kind = model.inputs[0]
  const items = kind === 'image' ? IMAGES : kind === 'text' ? [] : DATASETS.filter((d) => d.modality === kind).flatMap((d) => (d.collection ? d.collection.map((c) => c.id) : d.sample.map((r) => String(r[0])))).slice(0, 4)
  const [text, setText] = useState(TEXT_SAMPLES[0])
  const [item, setItem] = useState(items[0] ?? '')
  const [result, setResult] = useState<Result | null>(null)

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t('models.widget.hint')}</p>
      {kind === 'text' ? (
        <div className="space-y-2">
          <Textarea rows={3} value={text} aria-label={t('models.widget.input')} onChange={(e) => { setText(e.target.value); setResult(null) }} />
          <div className="flex flex-wrap gap-1.5">{TEXT_SAMPLES.map((s, i) => <Button key={i} size="sm" variant="ghost" onClick={() => { setText(s); setResult(null) }}>{t('models.widget.example', { n: i + 1 })}</Button>)}</div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((i) => <Button key={i} size="sm" variant={item === i ? 'default' : 'outline'} onClick={() => { setItem(i); setResult(null) }}>{i}</Button>)}
          {!items.length && <p className="text-sm text-muted-foreground">{t('models.widget.noSample')}</p>}
        </div>
      )}
      <Button onClick={() => setResult(predict(model, kind === 'text' ? text : item))} disabled={kind !== 'text' && !item}><Play />{t('models.widget.run')}</Button>

      {result && (
        <div className="space-y-2 rounded-lg border p-3" aria-live="polite">
          <h3 className="text-sm font-medium">{t('models.widget.result')}</h3>
          {result.kind === 'scores' && result.items.map((s) => (
            <div key={s.label} className="flex items-center gap-2 text-sm">
              <span className="w-24 truncate">{s.label}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${s.score * 100}%` }} /></div>
              <span className="w-12 text-right font-mono text-xs">{Math.round(s.score * 100)} %</span>
            </div>
          ))}
          {result.kind === 'spans' && (
            <p className="leading-8">
              {result.tokens.map((tok, i) => {
                const sp = result.spans.find((x) => i >= x.start && i <= x.end)
                return <span key={i}><span className={cn(sp && 'rounded border px-1')} style={sp ? { background: `hsl(${hue(sp.label)} 80% 88%)`, borderColor: `hsl(${hue(sp.label)} 60% 55%)`, color: `hsl(${hue(sp.label)} 60% 20%)` } : undefined}>{tok}{sp && sp.end === i && <sup className="ml-1 text-[10px] font-semibold">{sp.label}</sup>}</span>{' '}</span>
              })}
            </p>
          )}
          {result.kind === 'text' && <p className="text-sm">{result.text}</p>}
          {result.kind === 'value' && <p className="font-mono text-2xl">{result.value}</p>}
          {result.kind === 'lines' && <ul className="space-y-1 font-mono text-xs">{result.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
          {result.kind === 'boxes' && (
            <svg viewBox="0 0 1280 720" className="block w-full rounded border" role="img" aria-label={result.file}>
              <SceneGraphics file={result.file} width={1280} height={720} />
              {result.boxes.map((b, i) => (
                <g key={i}>
                  <rect x={b.x} y={b.y} width={b.w} height={b.h} fill="none" stroke={`hsl(${hue(b.label)} 75% 45%)`} strokeWidth={4} />
                  <text x={b.x} y={b.y - 8} fontSize={28} fontWeight={600} fill="white" stroke="black" strokeWidth={5} paintOrder="stroke">{b.label}</text>
                </g>
              ))}
            </svg>
          )}
          <p className="text-xs text-muted-foreground">{t('models.widget.simulated')}</p>
        </div>
      )}
    </div>
  )
}
